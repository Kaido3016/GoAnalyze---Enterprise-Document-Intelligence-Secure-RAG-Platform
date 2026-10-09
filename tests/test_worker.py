from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gov_platform import worker
from gov_platform.db.models import DocumentORM, ProcessingJobORM
from gov_platform.models import DocumentProcessingResult


def _sessionmaker(db_engine):
    return async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)


async def test_claim_job_marks_queued_job_processing(db_engine, db_session, monkeypatch):
    maker = _sessionmaker(db_engine)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    job = ProcessingJobORM(
        tenant_id="tenant-a",
        document_id=uuid4(),
        actor="worker-test",
        trace_id="trace-test",
        purpose="case-review",
        status="queued",
    )
    db_session.add(job)
    await db_session.commit()

    claimed_id = await worker.claim_job()
    assert claimed_id == job.id
    async with maker() as session:
        claimed = await session.get(ProcessingJobORM, job.id)
        assert claimed is not None
        assert claimed.status == "processing"
        assert claimed.attempts == 1


async def test_claim_job_fails_stale_job_after_retry_limit(db_engine, db_session, monkeypatch):
    maker = _sessionmaker(db_engine)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    job = ProcessingJobORM(
        tenant_id="tenant-a",
        document_id=uuid4(),
        actor="worker-test",
        trace_id="trace-test",
        purpose="case-review",
        status="processing",
        attempts=3,
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(job)
    await db_session.commit()

    assert await worker.claim_job() is None
    async with maker() as session:
        failed = await session.get(ProcessingJobORM, job.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_code == "worker_lease_expired"


async def test_process_job_marks_missing_document_failed(db_engine, db_session, monkeypatch):
    maker = _sessionmaker(db_engine)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    job = ProcessingJobORM(
        tenant_id="tenant-a",
        document_id=uuid4(),
        actor="worker-test",
        trace_id="trace-test",
        purpose="case-review",
        status="processing",
        attempts=1,
        started_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.commit()

    await worker.process_job(job.id)
    async with maker() as session:
        failed = await session.get(ProcessingJobORM, job.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_code == "RuntimeError"


async def test_process_job_persists_successful_pipeline_result(db_engine, db_session, monkeypatch):
    maker = _sessionmaker(db_engine)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    document = DocumentORM(
        tenant_id="tenant-a",
        filename="permit.txt",
        content_type="text/plain",
        classification="internal",
        sha256="a" * 64,
        object_uri="object://tenant-a/document",
    )
    db_session.add(document)
    await db_session.flush()
    job = ProcessingJobORM(
        tenant_id="tenant-a",
        document_id=document.id,
        actor="worker-test",
        trace_id="trace-test",
        purpose="case-review",
        status="processing",
        attempts=1,
        started_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.commit()

    class FakeStorage:
        async def get(self, key):
            assert key
            return b"permit text"

    async def fake_storage():
        return FakeStorage()

    async def fake_run(**kwargs):
        assert kwargs["raw_bytes"] == b"permit text"
        return DocumentProcessingResult(document_id=document.id, completed=True, status="completed")

    monkeypatch.setattr(worker, "get_object_storage", fake_storage)
    monkeypatch.setattr(worker.ingestion_pipeline, "run", fake_run)
    await worker.process_job(job.id)

    async with maker() as session:
        finished = await session.get(ProcessingJobORM, job.id)
        assert finished is not None
        assert finished.status == "succeeded"
        assert finished.result["status"] == "completed"
        assert finished.finished_at is not None
