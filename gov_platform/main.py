import hashlib
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response, StreamingResponse

from . import search as search_service
from .audit import audit_log
from .config import get_settings
from .db.repositories import CaseRepository, DocumentRepository
from .db.session import get_session
from .environmental_engine import engine
from .ingestion import ingestion_pipeline
from .models import (
    AuditEvent,
    AuditEventListResponse,
    ClassificationLevel,
    DocumentIngestRequest,
    DocumentProcessingResult,
    DocumentRecord,
    EnvironmentalReviewRequest,
    EvidenceCitation,
    SearchResponse,
    SetupConfiguration,
    SetupConfigurationResult,
    TenantContext,
)
from .rag import rag_service
from .rate_limit import enforce_ip_rate_limit
from .security import evaluate_abac, get_current_context
from .storage import (
    ObjectNotFoundError,
    ObjectStorageBackend,
    StorageUnavailableError,
    get_object_storage,
    storage_key,
)
from .workflows import assignment_engine

settings = get_settings()

# Buffered fully in memory (see upload_document_content), so this is a
# real ceiling, not a soft guideline. Raise via reverse-proxy streaming
# upload support before raising this much further.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _content_disposition(filename: str) -> str:
    """RFC 6266-safe Content-Disposition header value.

    Strips CR/LF (header-injection) and quotes, and percent-encodes the
    filename into the `filename*` extended parameter so unicode/adversarial
    filenames can never break out of the header or misrepresent the
    download's name."""
    from urllib.parse import quote

    safe = filename.replace("\r", "").replace("\n", "").replace('"', "")
    ascii_fallback = safe.encode("ascii", errors="replace").decode("ascii")
    encoded = quote(safe, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Development convenience only.

    Real deployments (staging/production) must provision schema via
    ``alembic upgrade head`` as part of the release pipeline; table
    auto-creation is intentionally a no-op outside
    ``environment=development`` so schema drift can never be silently
    masked in a real environment.
    """
    if settings.environment == "development":
        from .db.models import Base
        from .db.session import get_engine

        engine_ = get_engine()
        async with engine_.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # Flush any buffered spans (BatchSpanProcessor exports asynchronously
    # on a timer) before the process actually exits, so a graceful
    # shutdown never silently drops the tail end of a trace.
    try:
        from opentelemetry import trace as _trace

        provider = _trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        logging.getLogger("gov_platform").warning("OpenTelemetry shutdown flush failed", exc_info=True)


app = FastAPI(
    title="GoAnalyze Government Document Intelligence Platform",
    version="2.0.0",
    description="Document intelligence API with audit, ABAC, search, and decision-support workflows. Grounded generation and vector retrieval require configured providers.",
    lifespan=_lifespan,
)

# Request tracing. Auto-instruments FastAPI routes, outbound httpx calls
# (JWKS fetches, OpenSearch REST calls), and SQLAlchemy queries with spans,
# and propagates W3C traceparent context end to end.
#
# Exporter selection is detected at runtime, not assumed:
#   - If GOV_OTEL_EXPORTER_OTLP_ENDPOINT is set AND the OTLP exporter
#     package is actually importable, spans are exported via OTLP.
#   - Otherwise, spans are exported to the console in development (useful
#     without a collector running) or simply not exported at all outside
#     development (spans are still created -- cheap -- just not shipped
#     anywhere, so there's no dangling behavior to explain).
# Every step is independently wrapped so a missing/broken piece of the
# tracing stack degrades that one piece rather than blocking startup.
def _init_tracing() -> None:
    import os

    if not settings.otel_tracing_enabled:
        logging.getLogger("gov_platform").info("OpenTelemetry: tracing explicitly disabled via GOV_OTEL_TRACING_ENABLED=false.")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logging.getLogger("gov_platform").info("OpenTelemetry SDK not installed; tracing disabled.")
        return

    provider = TracerProvider(resource=Resource(attributes={SERVICE_NAME: settings.service_name}))

    otlp_endpoint = os.environ.get("GOV_OTEL_EXPORTER_OTLP_ENDPOINT")
    exporter_configured = False
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            exporter_configured = True
            logging.getLogger("gov_platform").info("OpenTelemetry: exporting spans via OTLP to %s", otlp_endpoint)
        except ImportError:
            logging.getLogger("gov_platform").warning(
                "GOV_OTEL_EXPORTER_OTLP_ENDPOINT is set but the OTLP exporter package "
                "(opentelemetry-exporter-otlp-proto-grpc) is not installed; falling back."
            )
    if not exporter_configured and settings.environment == "development":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logging.getLogger("gov_platform").info("OpenTelemetry: exporting spans to console (development fallback).")
    elif not exporter_configured:
        logging.getLogger("gov_platform").info(
            "OpenTelemetry: no exporter configured (set GOV_OTEL_EXPORTER_OTLP_ENDPOINT); spans created but not exported."
        )

    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        logging.getLogger("gov_platform").info("opentelemetry-instrumentation-fastapi not installed; FastAPI spans disabled.")
    except Exception:
        logging.getLogger("gov_platform").warning("FastAPI instrumentation failed to initialize", exc_info=True)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logging.getLogger("gov_platform").info("opentelemetry-instrumentation-httpx not installed; outbound HTTP spans disabled.")
    except Exception:
        logging.getLogger("gov_platform").warning("httpx instrumentation failed to initialize", exc_info=True)

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from .db.session import get_engine

        SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    except ImportError:
        logging.getLogger("gov_platform").info("opentelemetry-instrumentation-sqlalchemy not installed; DB spans disabled.")
    except Exception:
        logging.getLogger("gov_platform").warning("SQLAlchemy instrumentation failed to initialize", exc_info=True)


try:
    _init_tracing()
except Exception:  # pragma: no cover - tracing must never block app startup
    logging.getLogger("gov_platform").warning("OpenTelemetry instrumentation failed to initialize", exc_info=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["authorization", "content-type", "x-tenant-id", "x-roles", "x-ministry", "x-purpose"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.environment != "development":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.middleware("http")
async def ip_rate_limit(request: Request, call_next):
    if request.url.path not in {"/health", "/ready", "/metrics"}:
        try:
            await enforce_ip_rate_limit(request)
        except HTTPException as exc:
            from starlette.responses import JSONResponse

            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    return await call_next(request)


REQUESTS = Counter("goanalyze_api_requests_total", "Total API requests", ["path"])


@app.middleware("http")
async def count_requests(request: Request, call_next):
    REQUESTS.labels(path=request.url.path).inc()
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving requests. Deliberately
    does not touch the database or any external dependency, so it stays
    healthy (and orchestrators don't kill/restart the pod) during a
    transient outage of something the app can recover from on its own."""
    return {"status": "ok", "service": settings.service_name, "environment": settings.environment}


@app.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> Response:
    """Readiness probe: can this instance actually serve real traffic right
    now? Checks the database connection specifically, since that's a hard
    dependency for nearly every route. Returns 503 (not 200) when it can't,
    which is what a load balancer/orchestrator should act on to stop
    routing traffic here -- unlike /health, which intentionally does not
    reflect this."""
    from sqlalchemy import text

    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness probe must catch any DB failure mode
        return Response(
            content='{"status":"not_ready","reason":"database_unreachable"}',
            media_type="application/json",
            status_code=503,
        )
    return Response(content='{"status":"ready"}', media_type="application/json", status_code=200)


@app.exception_handler(StorageUnavailableError)
async def storage_unavailable_handler(request: Request, exc: StorageUnavailableError) -> Response:
    """Expose storage outages as a retryable service-unavailable response."""
    logging.getLogger("gov_platform").error(
        "Durable object storage unavailable on %s %s", request.method, request.url.path
    )
    return Response(
        content='{"detail":"object_storage_unavailable"}',
        media_type="application/json",
        status_code=503,
        headers={"Retry-After": "30"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Never leak a bare framework error page or a stack trace to the
    client. Logs the real exception server-side; the client gets a
    generic, structured message.

    Deliberately re-delegates HTTPException (401/403/404/422/etc, raised
    intentionally throughout the app) to FastAPI's own default handler --
    only genuinely unexpected exceptions get the generic 500 treatment.
    """
    from fastapi.exception_handlers import http_exception_handler

    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)

    logging.getLogger("gov_platform").exception("Unhandled exception on %s %s", request.method, request.url.path)
    return Response(
        content='{"detail":"internal_server_error"}',
        media_type="application/json",
        status_code=500,
    )


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/documents", response_model=DocumentRecord)
async def ingest_document(
    payload: DocumentIngestRequest,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> DocumentRecord:
    purpose = request.headers.get("x-purpose", "case-review")
    decision = evaluate_abac(context, "document:ingest", payload.tenant_id, payload.classification, purpose)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    record = DocumentRecord(**payload.model_dump())
    # The client-provided URI is never authoritative. Allocate a stable,
    # server-controlled object key before persisting the document record.
    record.object_uri = f"object://{storage_key(record.tenant_id, record.id)}"
    await DocumentRepository(session).create(record)
    await search_service.index_document(record)
    await audit_log.append(
        session,
        AuditEvent(
            tenant_id=record.tenant_id,
            actor=context.attributes.get("sub", "api-user"),
            action="document.ingested",
            resource_type="document",
            resource_id=str(record.id),
            purpose=purpose,
            trace_id=request.headers.get("traceparent", "local-trace"),
            details={"sha256": record.sha256, "classification": record.classification},
        ),
    )
    return record


@app.post("/v1/setup", response_model=SetupConfigurationResult)
async def submit_setup_configuration(payload: SetupConfiguration) -> SetupConfigurationResult:
    """Validate the request shape only; this endpoint does not persist secrets,
    test connectivity, or configure external services."""
    # Do not report requested services as validated when no live checks ran.
    validated: list[str] = []
    warnings: list[str] = [
        "configuration_received_only; no connectivity checks or persistence performed"
    ]
    if payload.identity_provider == "keycloak" and not payload.keycloak_issuer:
        warnings.append("keycloak_issuer_missing")
    if payload.identity_provider == "azure_ad" and not (payload.azure_ad_tenant_id and payload.azure_ad_client_id):
        warnings.append("azure_ad_credentials_incomplete")
    if payload.identity_provider == "microsoft_entra_id" and not payload.microsoft_entra_id_tenant_id:
        warnings.append("microsoft_entra_id_tenant_missing")
    if payload.email_notifications_enabled and not (
        payload.email_smtp_host and payload.email_from_address
    ):
        warnings.append("email_notification_settings_incomplete")
    return SetupConfigurationResult(accepted=True, validated_components=validated, warnings=warnings)


@app.post("/v1/documents/{document_id}/process", response_model=DocumentProcessingResult)
async def process_document(
    document_id: UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> DocumentProcessingResult:
    """Run the native ingestion pipeline: OCR, classification, metadata and
    entity extraction, compliance analysis, risk scoring, vector indexing,
    workflow routing, and audit logging."""
    record = await DocumentRepository(session).get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    purpose = request.headers.get("x-purpose", "case-review")
    decision = evaluate_abac(context, "document:process", record.tenant_id, record.classification, purpose)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return await ingestion_pipeline.run(
        record=record,
        actor=context.attributes.get("sub", "api-user"),
        trace_id=request.headers.get("traceparent", "local-trace"),
        purpose=purpose,
        session=session,
    )


@app.post("/v1/rag/answer")
async def rag_answer(
    question: str,
    citations: list[EvidenceCitation],
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Answer a question grounded in the supplied evidence citations.

    Every cited document is re-fetched from the tenant-scoped document store
    and its ownership verified before the citation is trusted: a caller
    cannot get a grounded answer that leans on a document belonging to a
    different tenant just by forging a ``document_id`` in the request body.
    """
    repository = DocumentRepository(session)
    document_ids = [citation.document_id for citation in citations]
    documents = await repository.get_many(document_ids)

    for citation in citations:
        record = documents.get(citation.document_id)
        if record is None:
            raise HTTPException(status_code=403, detail="citation_document_not_found")
        if record.tenant_id != context.tenant_id and "platform-admin" not in context.roles:
            raise HTTPException(status_code=403, detail="citation_tenant_mismatch")
        if record.version != citation.version or record.sha256.lower() != citation.sha256.lower():
            raise HTTPException(status_code=422, detail="citation_version_or_digest_mismatch")
        if record.classification.value == "protected_b" and "protected-b-reader" not in context.roles:
            raise HTTPException(status_code=403, detail="protected_b_role_required")

    finding = rag_service.answer(question, citations)

    await audit_log.append(
        session,
        AuditEvent(
            tenant_id=context.tenant_id,
            actor=context.attributes.get("sub", "api-user"),
            action="rag.answer_generated" if finding.grounded else "rag.answer_unavailable",
            resource_type="rag_query",
            resource_id=",".join(str(cid) for cid in document_ids) or "none",
            purpose=request.headers.get("x-purpose", "case-review"),
            trace_id=request.headers.get("traceparent", "local-trace"),
            details={"grounded": finding.grounded, "citation_count": len(citations)},
        ),
    )

    return finding.model_dump(mode="json")


@app.post("/v1/environmental-reviews")
async def environmental_review(
    payload: EnvironmentalReviewRequest,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if context.tenant_id != payload.tenant_id and "platform-admin" not in context.roles:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    repository = DocumentRepository(session)
    documents = await repository.get_many(payload.documents)
    missing_ids = set(payload.documents) - set(documents)
    if missing_ids:
        raise HTTPException(status_code=404, detail="review_document_not_found")
    for document in documents.values():
        # A review may only use documents belonging to the review tenant,
        # even for platform administrators; mixed-tenant evidence is rejected.
        if document.tenant_id != payload.tenant_id:
            raise HTTPException(status_code=403, detail="review_document_tenant_mismatch")
        document_decision = evaluate_abac(
            context,
            "document:read",
            document.tenant_id,
            document.classification,
            request.headers.get("x-purpose", "case-review"),
        )
        if not document_decision.allowed:
            raise HTTPException(status_code=403, detail=document_decision.reason)

    available_types = {
        str(documents[doc_id].metadata.get("document_type"))
        for doc_id in payload.documents
        if doc_id in documents and documents[doc_id].metadata.get("document_type")
    }
    citations = [
        EvidenceCitation(
            document_id=doc_id,
            version=documents[doc_id].version,
            chunk_id=f"{doc_id}:metadata",
            sha256=documents[doc_id].sha256,
            excerpt=f"{documents[doc_id].filename} supplied for {payload.project_type}",
        )
        for doc_id in payload.documents
        if doc_id in documents
    ]
    result = engine.review(payload, available_types, citations)
    await audit_log.append(
        session,
        AuditEvent(
            tenant_id=payload.tenant_id,
            actor=context.attributes.get("sub", "api-user"),
            action="environmental_review.completed",
            resource_type="case",
            resource_id=str(payload.case_id),
            purpose=request.headers.get("x-purpose", "case-review"),
            trace_id=request.headers.get("traceparent", "local-trace"),
            details={"risk_score": result.risk_score, "recommendation": result.recommendation},
        ),
    )
    return result.model_dump(mode="json")


@app.post("/v1/cases/{case_id}/assign")
async def assign_case(
    case_id: UUID,
    skill: str = "technical",
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if "case-manager" not in context.roles and "tenant-admin" not in context.roles:
        raise HTTPException(status_code=403, detail="case_manager_role_required")
    assignment = assignment_engine.assign(case_id, skill, {"analyst-1": 3, "analyst-2": 1})
    await CaseRepository(session).create_assignment(
        case_id=assignment.case_id,
        tenant_id=context.tenant_id,
        assignee=assignment.assignee,
        queue=assignment.queue,
        status=assignment.status.value,
        due_at=assignment.due_at,
        escalation_at=assignment.escalation_at,
    )
    return {
        "case_id": str(assignment.case_id),
        "assignee": assignment.assignee,
        "queue": assignment.queue,
        "due_at": assignment.due_at.isoformat(),
        "escalation_at": assignment.escalation_at.isoformat(),
        "status": assignment.status,
    }


@app.get("/v1/audit", response_model=AuditEventListResponse)
async def list_audit(
    page: int = 1,
    page_size: int = 20,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> AuditEventListResponse:
    if page < 1:
        raise HTTPException(status_code=422, detail="page_must_be_positive")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size_must_be_between_1_and_100")
    items, total = await audit_log.list_events_paginated(session, context.tenant_id, page, page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return AuditEventListResponse(total=total, page=page, page_size=page_size, total_pages=total_pages, items=items)


@app.get("/v1/documents/search", response_model=SearchResponse)
async def search_documents(
    q: str = "",
    page: int = 1,
    page_size: int = 20,
    classification: str | None = None,
    content_type: str | None = None,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """Full-text document search, always scoped server-side to the caller's
    tenant. Backed by OpenSearch when reachable (relevance-ranked, with
    highlighting); automatically falls back to a database search
    (recency-ordered) if OpenSearch is unavailable, so the endpoint keeps
    working during a search-cluster outage."""
    if page < 1:
        raise HTTPException(status_code=422, detail="page_must_be_positive")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size_must_be_between_1_and_100")
    return await search_service.search(
        session,
        tenant_id=context.tenant_id,
        query=q,
        page=page,
        page_size=page_size,
        classification=classification,
        content_type=content_type,
    )


@app.get("/v1/documents")
async def list_documents(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    classification: str | None = None,
    content_type: str | None = None,
    case_id: UUID | None = None,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List documents visible to the authenticated tenant, newest first."""
    if page < 1:
        raise HTTPException(status_code=422, detail="page_must_be_positive")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size_must_be_between_1_and_100")
    purpose = request.headers.get("x-purpose", "case-review")
    purpose_decision = evaluate_abac(
        context, "document:read", context.tenant_id, 
        ClassificationLevel.internal,
        purpose,
    )
    if not purpose_decision.allowed:
        raise HTTPException(status_code=403, detail=purpose_decision.reason)
    records, total = await DocumentRepository(session).list_for_tenant(
        tenant_id=context.tenant_id,
        page=page,
        page_size=page_size,
        classification=classification,
        content_type=content_type,
        case_id=case_id,
        exclude_protected_b="protected-b-reader" not in context.roles,
    )
    return {
        "items": [record.model_dump(mode="json") for record in records],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@app.get("/v1/documents/{document_id}", response_model=DocumentRecord)
async def get_document(
    document_id: UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> DocumentRecord:
    """Fetch one document after tenant and classification authorization."""
    record = await DocumentRepository(session).get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    purpose = request.headers.get("x-purpose", "case-review")
    decision = evaluate_abac(context, "document:read", record.tenant_id, record.classification, purpose)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return record


@app.put("/v1/documents/{document_id}/content")
async def upload_document_content(
    document_id: UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
    storage: ObjectStorageBackend = Depends(get_object_storage),
) -> dict:
    """Upload the original file bytes for a previously-ingested document
    record. The storage key is always derived server-side from
    (tenant_id, document_id) -- the client-supplied ``object_uri`` on the
    document record is never used to address storage, so it cannot be
    abused for path traversal or to overwrite another tenant's object."""
    record = await DocumentRepository(session).get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    purpose = request.headers.get("x-purpose", "case-review")
    decision = evaluate_abac(context, "document:upload", record.tenant_id, record.classification, purpose)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    # Consume the request incrementally and enforce the cap while reading;
    # Request.body() would buffer an arbitrarily large attacker-controlled body
    # before this endpoint could reject it. The storage interface still accepts
    # bytes, so the accepted (<=100 MiB) payload is buffered once for persistence.
    body_buffer = bytearray()
    async for chunk in request.stream():
        if len(body_buffer) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload_too_large")
        body_buffer.extend(chunk)
    if not body_buffer:
        raise HTTPException(status_code=422, detail="empty_upload_body")

    digest = hashlib.sha256(body_buffer).hexdigest()
    body = bytes(body_buffer)
    del body_buffer
    if digest != record.sha256:
        raise HTTPException(status_code=422, detail="sha256_mismatch")

    key = storage_key(record.tenant_id, record.id)
    await storage.put(key, body, record.content_type)

    await audit_log.append(
        session,
        AuditEvent(
            tenant_id=record.tenant_id,
            actor=context.attributes.get("sub", "api-user"),
            action="document.content_uploaded",
            resource_type="document",
            resource_id=str(record.id),
            purpose=purpose,
            trace_id=request.headers.get("traceparent", "local-trace"),
            details={"bytes": len(body)},
        ),
    )
    return {"document_id": str(record.id), "bytes_stored": len(body), "sha256": digest}


@app.get("/v1/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
    storage: ObjectStorageBackend = Depends(get_object_storage),
) -> StreamingResponse:
    """Stream the original file bytes back to an authorized caller, with
    the document's own content type and a Content-Disposition filename."""
    record = await DocumentRepository(session).get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    purpose = request.headers.get("x-purpose", "case-review")
    decision = evaluate_abac(context, "document:download", record.tenant_id, record.classification, purpose)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    key = storage_key(record.tenant_id, record.id)
    try:
        data = await storage.get(key)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document_content_not_uploaded") from exc

    await audit_log.append(
        session,
        AuditEvent(
            tenant_id=record.tenant_id,
            actor=context.attributes.get("sub", "api-user"),
            action="document.downloaded",
            resource_type="document",
            resource_id=str(record.id),
            purpose=purpose,
            trace_id=request.headers.get("traceparent", "local-trace"),
            details={"bytes": len(data)},
        ),
    )

    async def _stream():
        yield data

    return StreamingResponse(
        _stream(),
        media_type=record.content_type,
        headers={"Content-Disposition": _content_disposition(record.filename)},
    )
