"""SQLAlchemy ORM models backing the GoAnalyze persistence layer.

Column types are chosen to be portable across PostgreSQL (production, via
asyncpg) and SQLite (used for offline/CI testing via aiosqlite) so the same
model definitions and Alembic migration can be exercised in both
environments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DocumentORM(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_id", "tenant_id"),
        Index("ix_documents_tenant_id_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(nullable=True)
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lineage_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CaseAssignmentORM(Base):
    __tablename__ = "case_assignments"
    __table_args__ = (Index("ix_case_assignments_case_id", "case_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    assignee: Mapped[str] = mapped_column(String(255), nullable=False)
    queue: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class UserORM(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_tenant_id", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ministry: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class AuditEventORM(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_id", "tenant_id"),
        Index("ix_audit_events_tenant_id_timestamp_id", "tenant_id", "timestamp", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditChainStateORM(Base):
    """One row per tenant, tracking the current head of that tenant's audit
    hash chain. ``AuditRepository.append`` takes a ``SELECT ... FOR UPDATE``
    row lock on this table (not on ``audit_events`` itself) before reading
    the head and writing the next event, which serializes concurrent
    appends *per tenant* via standard Postgres row-level locking -- see
    ROOT_CAUSE_ANALYSIS.md / FINAL_DATABASE_AUDIT.md for why this replaced
    an earlier advisory-lock-based attempt."""

    __tablename__ = "audit_chain_state"

    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    latest_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

class CaseORM(Base):
    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_tenant_created", "tenant_id", "created_at"),
        Index("ix_cases_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    project_type: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str] = mapped_column(String(512), nullable=False)
    applicant: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="intake")
    risk_score: Mapped[float | None] = mapped_column(nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class DocumentChunkORM(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
        Index("ix_document_chunks_tenant_classification", "tenant_id", "classification"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProcessingJobORM(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_status_created", "status", "created_at"),
        Index("ix_processing_jobs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegulatorySourceORM(Base):
    __tablename__ = "regulatory_sources"
    __table_args__ = (
        Index("ix_regulatory_sources_jurisdiction_status", "jurisdiction", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    official_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    authority_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="catalogued_not_ingested")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
