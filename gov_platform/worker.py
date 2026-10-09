"""Durable PostgreSQL-backed document processing worker.

Run one or more replicas with `python -m gov_platform.worker`. PostgreSQL
row locks with SKIP LOCKED prevent replicas from claiming the same job.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from .db.models import ProcessingJobORM
from .db.repositories import DocumentRepository
from .db.session import get_sessionmaker
from .ingestion import ingestion_pipeline
from .storage import ObjectNotFoundError, get_object_storage, storage_key

logger = logging.getLogger("gov_platform.worker")
POLL_SECONDS = 1.0
STALE_AFTER = timedelta(minutes=20)
MAX_ATTEMPTS = 3


async def claim_job():
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            now = datetime.now(UTC)
            result = await session.execute(
                select(ProcessingJobORM)
                .where(
                    or_(
                        ProcessingJobORM.status == "queued",
                        (
                            (ProcessingJobORM.status == "processing")
                            & (ProcessingJobORM.started_at < now - STALE_AFTER)
                            & (ProcessingJobORM.attempts < MAX_ATTEMPTS)
                        ),
                    )
                )
                .order_by(ProcessingJobORM.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "processing"
            job.attempts += 1
            job.started_at = now
            job.finished_at = None
            job.error_code = None
            await session.flush()
            return job.id


async def process_job(job_id) -> None:
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            job = await session.get(ProcessingJobORM, job_id)
            if job is None or job.status != "processing":
                return
            record = await DocumentRepository(session).get(job.document_id)
            if record is None or record.tenant_id != job.tenant_id:
                raise RuntimeError("document_not_found_or_tenant_mismatch")
            storage = await get_object_storage()
            try:
                data = await storage.get(storage_key(record.tenant_id, record.id))
            except ObjectNotFoundError as exc:
                raise RuntimeError("document_content_missing") from exc
            result = await ingestion_pipeline.run(
                record=record,
                actor=job.actor,
                trace_id=job.trace_id,
                purpose=job.purpose,
                session=session,
                raw_bytes=data,
            )
            job = await session.get(ProcessingJobORM, job_id)
            if job is None:
                return
            job.status = "succeeded" if result.status == "completed" else "completed_with_warnings"
            job.result = result.model_dump(mode="json")
            job.finished_at = datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        logger.exception("Document processing job failed", extra={"job_id": str(job_id)})
        async with sessionmaker() as session:
            job = await session.get(ProcessingJobORM, job_id)
            if job is not None:
                job.status = "failed"
                job.error_code = type(exc).__name__
                job.finished_at = datetime.now(UTC)
                await session.commit()


async def run_worker() -> None:
    logger.info("GoAnalyze document worker started")
    while True:
        try:
            job_id = await claim_job()
            if job_id is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            await process_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker polling cycle failed")
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
