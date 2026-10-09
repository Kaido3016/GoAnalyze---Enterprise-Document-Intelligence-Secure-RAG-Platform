"""add durable cases, embeddings/chunks, async jobs, and source registry

Revision ID: b47d3b9a1c21
Revises: ed3a4f8a50b6
Create Date: 2026-10-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b47d3b9a1c21"
down_revision: str | Sequence[str] | None = "ed3a4f8a50b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("project_type", sa.String(128), nullable=False),
        sa.Column("location", sa.String(512), nullable=False),
        sa.Column("applicant", sa.String(512), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(128), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_tenant_created", "cases", ["tenant_id", "created_at"])
    op.create_index("ix_cases_tenant_status", "cases", ["tenant_id", "status"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_chunks_tenant_document", "document_chunks", ["tenant_id", "document_id"])
    op.create_index("ix_document_chunks_tenant_classification", "document_chunks", ["tenant_id", "classification"])

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("trace_id", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_jobs_status_created", "processing_jobs", ["status", "created_at"])
    op.create_index("ix_processing_jobs_tenant_created", "processing_jobs", ["tenant_id", "created_at"])

    op.create_table(
        "regulatory_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("official_url", sa.String(2048), nullable=False),
        sa.Column("authority_domain", sa.String(255), nullable=False),
        sa.Column("source_version", sa.String(255), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("content_text", sa.String(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("official_url"),
    )
    op.create_index("ix_regulatory_sources_jurisdiction_status", "regulatory_sources", ["jurisdiction", "status"])

    op.create_table(
        "regulatory_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regulatory_chunks_source", "regulatory_chunks", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_regulatory_chunks_source", table_name="regulatory_chunks")
    op.drop_table("regulatory_chunks")
    op.drop_index("ix_regulatory_sources_jurisdiction_status", table_name="regulatory_sources")
    op.drop_table("regulatory_sources")
    op.drop_index("ix_processing_jobs_tenant_created", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_status_created", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_document_chunks_tenant_classification", table_name="document_chunks")
    op.drop_index("ix_document_chunks_tenant_document", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_cases_tenant_status", table_name="cases")
    op.drop_index("ix_cases_tenant_created", table_name="cases")
    op.drop_table("cases")
