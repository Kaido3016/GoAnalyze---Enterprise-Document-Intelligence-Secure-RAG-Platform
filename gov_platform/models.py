from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ClassificationLevel(StrEnum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    protected_b = "protected_b"


class ReviewStatus(StrEnum):
    intake = "intake"
    admissibility = "admissibility"
    technical_review = "technical_review"
    legal_review = "legal_review"
    awaiting_information = "awaiting_information"
    recommendation = "recommendation"
    approved = "approved"
    rejected = "rejected"


class TenantContext(BaseModel):
    tenant_id: str
    ministry: str
    roles: set[str] = Field(default_factory=set)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DocumentIngestRequest(BaseModel):
    tenant_id: str
    case_id: UUID | None = None
    filename: str
    content_type: str
    classification: ClassificationLevel = ClassificationLevel.internal
    sha256: str = Field(min_length=64, max_length=64)
    object_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(DocumentIngestRequest):
    id: UUID = Field(default_factory=uuid4)
    version: int = 1
    lineage_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidenceCitation(BaseModel):
    document_id: UUID | None = None
    version: int = 1
    chunk_id: str
    page: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    sha256: str = ""
    excerpt: str
    regulatory_source_id: UUID | None = None
    source_title: str | None = None
    source_url: str | None = None


class AIFinding(BaseModel):
    finding_type: str
    statement: str
    confidence: float = Field(ge=0, le=1)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    grounded: bool
    explanation: str


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=512)
    project_type: str = Field(min_length=2, max_length=128)
    location: str = Field(min_length=2, max_length=512)
    applicant: str = Field(min_length=2, max_length=512)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CaseSummary(BaseModel):
    id: UUID
    tenant_id: str
    title: str
    project_type: str
    location: str
    applicant: str
    status: str
    risk_score: float | None = None
    recommendation: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0


class RegulatorySourceApprovalRequest(BaseModel):
    source_version: str = Field(min_length=1, max_length=255)
    reviewer_note: str = Field(min_length=10, max_length=2000)


class ProcessingJobSummary(BaseModel):
    id: UUID
    tenant_id: str
    document_id: UUID
    status: str
    attempts: int
    error_code: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EnvironmentalReviewRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=255)
    case_id: UUID
    project_type: str = Field(min_length=2, max_length=128)
    location: str = Field(min_length=2, max_length=512)
    applicant: str = Field(min_length=2, max_length=512)
    documents: list[UUID] = Field(max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=100)


class EnvironmentalReviewResult(BaseModel):
    case_id: UUID
    admissible: bool
    missing_documents: list[str]
    regulation_mappings: list[AIFinding]
    compliance_findings: list[AIFinding]
    risk_score: float | None = Field(default=None, ge=0, le=100)
    recommendation: str
    justification: str
    requires_human_review: bool


class IdentityProvider(StrEnum):
    keycloak = "keycloak"
    azure_ad = "azure_ad"
    microsoft_entra_id = "microsoft_entra_id"


class SetupConfiguration(BaseModel):
    postgresql_url: str
    minio_endpoint: str
    minio_access_key: str | None = None
    opensearch_url: str
    redis_url: str
    identity_provider: IdentityProvider
    keycloak_issuer: str | None = None
    azure_ad_tenant_id: str | None = None
    azure_ad_client_id: str | None = None
    microsoft_entra_id_tenant_id: str | None = None
    ocr_engine: str
    ai_provider: str
    ai_provider_endpoint: str | None = None
    object_storage_bucket: str
    email_notifications_enabled: bool = False
    email_smtp_host: str | None = None
    email_from_address: str | None = None


class SetupConfigurationResult(BaseModel):
    accepted: bool
    validated_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PipelineStage(StrEnum):
    upload = "upload"
    ocr = "ocr"
    classification = "classification"
    metadata_extraction = "metadata_extraction"
    entity_extraction = "entity_extraction"
    compliance_analysis = "compliance_analysis"
    risk_scoring = "risk_scoring"
    vector_indexing = "vector_indexing"
    workflow_engine = "workflow_engine"
    audit_logging = "audit_logging"


class StageResult(BaseModel):
    stage: PipelineStage
    status: str = "completed"
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


class DocumentProcessingResult(BaseModel):
    document_id: UUID
    stages: list[StageResult] = Field(default_factory=list)
    classification_label: str | None = None
    extracted_entities: list[str] = Field(default_factory=list)
    risk_score: float | None = None
    workflow_queue: str | None = None
    completed: bool = False
    # completed means orchestration terminated; this field communicates whether
    # every requested capability actually ran or one or more stages were skipped.
    status: str = "pending"


class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    purpose: str
    trace_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = None
    event_hash: str | None = None


class SearchHit(BaseModel):
    document_id: UUID
    filename: str
    content_type: str
    classification: ClassificationLevel
    score: float
    highlight: str | None = None
    created_at: datetime


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    page_size: int
    backend: str
    results: list[SearchHit] = Field(default_factory=list)


class AuditEventListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[AuditEvent] = Field(default_factory=list)


