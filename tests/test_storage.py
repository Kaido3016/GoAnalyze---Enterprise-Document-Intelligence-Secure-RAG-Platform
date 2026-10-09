from types import SimpleNamespace

import pytest

from gov_platform import storage


async def test_production_never_falls_back_to_process_local_storage(monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(
            environment="production",
            allow_in_memory_storage_fallback=True,
        ),
    )
    monkeypatch.setattr(storage, "_minio_backend_or_none", lambda: None)

    with pytest.raises(storage.StorageUnavailableError):
        await storage.get_object_storage()


async def test_development_fallback_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(
            environment="development",
            allow_in_memory_storage_fallback=False,
        ),
    )
    monkeypatch.setattr(storage, "_minio_backend_or_none", lambda: None)

    with pytest.raises(storage.StorageUnavailableError):
        await storage.get_object_storage()


async def test_development_fallback_is_available_when_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(
            environment="development",
            allow_in_memory_storage_fallback=True,
        ),
    )
    monkeypatch.setattr(storage, "_minio_backend_or_none", lambda: None)

    assert await storage.get_object_storage() is storage._fallback_store
