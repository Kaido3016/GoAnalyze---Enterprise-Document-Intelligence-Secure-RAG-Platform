"""Object storage for document bytes.

Storage keys are always derived server-side from ``tenant_id``/``document_id``
-- never from client-supplied fields like ``object_uri`` -- so a malicious or
malformed ``object_uri`` can never be used to influence where a file is
written or read from (no path traversal / SSRF surface via that field).

Two backends implement the same protocol:

* ``MinioObjectStorage`` -- the real backend, using the official ``minio``
  SDK against ``settings.minio_endpoint`` (S3-compatible; works against real
  MinIO or AWS S3 unchanged).
* ``InMemoryObjectStorage`` -- process-local storage for tests and explicitly
  opted-in local development only. It is never a silent production fallback.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from starlette.concurrency import run_in_threadpool

from .config import get_settings

logger = logging.getLogger(__name__)


class ObjectNotFoundError(Exception):
    pass


class StorageUnavailableError(RuntimeError):
    """Configured durable storage is unavailable; writes must not be acknowledged."""


class ObjectStorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...


@dataclass
class InMemoryObjectStorage:
    """Fallback / test backend: stores object bytes in a process-local dict."""

    _store: dict[str, tuple[bytes, str]]

    def __init__(self) -> None:
        self._store = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._store[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        if key not in self._store:
            raise ObjectNotFoundError(key)
        return self._store[key][0]

    async def exists(self, key: str) -> bool:
        return key in self._store


class MinioObjectStorage:
    """Real backend: the official MinIO SDK against a real MinIO/S3 endpoint."""

    def __init__(self, endpoint: str, access_key: str | None, secret_key: str | None, bucket: str, secure: bool) -> None:
        from minio import Minio  # imported lazily so tests never need it installed-and-configured

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket

    def _ensure_bucket_sync(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket_sync()
        self._client.put_object(self._bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)

    def _get_sync(self, key: str) -> bytes:
        from minio.error import S3Error

        try:
            response = self._client.get_object(self._bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                raise ObjectNotFoundError(key) from exc
            raise

    def _exists_sync(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._ensure_bucket_sync()
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await run_in_threadpool(self._put_sync, key, data, content_type)

    async def get(self, key: str) -> bytes:
        return await run_in_threadpool(self._get_sync, key)

    async def exists(self, key: str) -> bool:
        return await run_in_threadpool(self._exists_sync, key)


def storage_key(tenant_id: str, document_id: object) -> str:
    """Deterministic, server-controlled storage key -- never derived from
    client-supplied ``object_uri``."""
    return f"{tenant_id}/{document_id}"


_fallback_store = InMemoryObjectStorage()


@lru_cache
def _minio_backend_or_none() -> MinioObjectStorage | None:
    settings = get_settings()
    if not settings.minio_endpoint:
        return None
    try:
        return MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    except Exception:  # pragma: no cover - defensive, e.g. malformed endpoint
        logger.exception("MinIO client could not be initialized")
        return None


async def get_object_storage() -> ObjectStorageBackend:
    """Resolve durable storage, permitting volatile fallback only by explicit opt-in.

    Tests should inject a fresh ``InMemoryObjectStorage()`` through FastAPI's
    dependency overrides. A production outage must surface as unavailable rather
    than silently accepting data into a process-local dictionary.
    """
    settings = get_settings()

    def development_fallback(reason: str) -> ObjectStorageBackend:
        if settings.environment.lower() == "development" and settings.allow_in_memory_storage_fallback:
            logger.warning("Using explicitly enabled in-memory development storage: %s", reason)
            return _fallback_store
        raise StorageUnavailableError(
            "Durable object storage is unavailable. Configure MinIO/S3; "
            "volatile fallback is disabled."
        )

    backend = _minio_backend_or_none()
    if backend is None:
        return development_fallback("MinIO is not configured or could not be initialized")
    try:
        await backend.exists("__connectivity_probe__")
        return backend
    except Exception as exc:
        logger.exception("MinIO connectivity check failed")
        return development_fallback(type(exc).__name__)
