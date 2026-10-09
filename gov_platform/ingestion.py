"""Native document ingestion pipeline.

Every document processed by GoAnalyze moves through a fixed, auditable sequence
of stages. Each stage is independently pluggable (OCR engine, AI provider,
vector store, workflow engine) via configuration set through the enterprise
configuration wizard, but the sequence itself is a first-class part of the
platform and does not depend on any external document management system.

    Upload -> OCR -> Classification -> Metadata Extraction -> Entity Extraction
    -> Compliance Analysis -> Risk Scoring -> Vector Indexing -> Workflow Engine
    -> Audit Logging
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .audit import audit_log
from .environmental_engine import engine as compliance_engine
from .extraction import ExtractionUnavailable, extract_document_text
from .rag import ProviderUnavailable, rag_service
from .models import (
    AuditEvent,
    DocumentProcessingResult,
    DocumentRecord,
    EnvironmentalReviewRequest,
    EvidenceCitation,
    PipelineStage,
    StageResult,
)
from .workflows import assignment_engine

_ENTITY_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})*\b")

DOCUMENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "application_form": ("application", "form"),
    "site_plan": ("site plan", "drawing"),
    "effluent_characterization": ("effluent", "characterization"),
    "mitigation_plan": ("mitigation",),
    "public_consultation_record": ("consultation",),
    "waste_profile": ("waste profile",),
    "contingency_plan": ("contingency",),
    "closure_plan": ("closure",),
    "hydrogeology_report": ("hydrogeology",),
    "water_balance": ("water balance",),
    "impact_assessment": ("impact assessment",),
}


class OcrEngine(Protocol):
    def extract_text(self, data: bytes, content_type: str, filename: str) -> str:
        ...


class DocumentOcrEngine:
    """Extract text from native files and OCR scanned PDFs/images."""

    def extract_text(self, data: bytes, content_type: str, filename: str) -> str:
        return extract_document_text(data, content_type, filename)


@dataclass
class IngestionPipeline:
    ocr_engine: OcrEngine

    async def run(
        self,
        record: DocumentRecord,
        actor: str,
        trace_id: str,
        purpose: str,
        session: AsyncSession,
        raw_text: str | None = None,
        raw_bytes: bytes | None = None,
    ) -> DocumentProcessingResult:
        result = DocumentProcessingResult(document_id=record.id)

        result.stages.append(self._timed(PipelineStage.upload, self._stage_upload, record))

        ocr_stage, text = self._timed_with_output(
            PipelineStage.ocr, self._stage_ocr, record, raw_text, raw_bytes
        )
        result.stages.append(ocr_stage)

        classify_stage, label = self._timed_with_output(
            PipelineStage.classification, self._stage_classify, text
        )
        result.stages.append(classify_stage)
        result.classification_label = label

        metadata_stage, metadata = self._timed_with_output(
            PipelineStage.metadata_extraction, self._stage_metadata, record, text
        )
        result.stages.append(metadata_stage)

        entity_stage, entities = self._timed_with_output(
            PipelineStage.entity_extraction, self._stage_entities, text
        )
        result.stages.append(entity_stage)
        result.extracted_entities = entities

        compliance_stage, compliance_output = self._timed_with_output(
            PipelineStage.compliance_analysis,
            self._stage_compliance,
            record,
            label,
            metadata,
            text,
        )
        result.stages.append(compliance_stage)

        risk_stage, risk_score = self._timed_with_output(
            PipelineStage.risk_scoring, self._stage_risk, compliance_output
        )
        result.stages.append(risk_stage)
        result.risk_score = risk_score

        index_started = time.perf_counter()
        try:
            index_output = await rag_service.index_document(record, text, session)
        except Exception as exc:
            index_output = {
                "indexed": False,
                "reason": f"indexing_failed:{type(exc).__name__}",
                "__stage_status": "degraded",
            }
        index_status = index_output.pop("__stage_status", "completed")
        result.stages.append(
            StageResult(
                stage=PipelineStage.vector_indexing,
                status=index_status,
                output=index_output,
                duration_ms=(time.perf_counter() - index_started) * 1000,
            )
        )

        workflow_stage, queue = self._timed_with_output(
            PipelineStage.workflow_engine, self._stage_workflow, record, risk_score
        )
        result.stages.append(workflow_stage)
        result.workflow_queue = queue

        audit_stage = await self._timed_async(
            PipelineStage.audit_logging, self._stage_audit, record, actor, trace_id, purpose, result, session
        )
        result.stages.append(audit_stage)

        result.completed = True
        result.status = (
            "completed_with_warnings"
            if any(stage.status in {"skipped", "degraded", "failed"} for stage in result.stages)
            else "completed"
        )
        return result

    # -- stage implementations -------------------------------------------------

    def _stage_upload(self, record: DocumentRecord) -> dict[str, Any]:
        return {"object_uri": record.object_uri, "sha256": record.sha256}

    def _stage_ocr(
        self, record: DocumentRecord, raw_text: str | None, raw_bytes: bytes | None
    ) -> tuple[dict[str, Any], str]:
        if raw_text is not None:
            text = raw_text
        elif raw_bytes is not None:
            try:
                text = self.ocr_engine.extract_text(raw_bytes, record.content_type, record.filename)
            except (ExtractionUnavailable, ValueError) as exc:
                return {
                    "character_count": 0,
                    "reason": str(exc),
                    "__stage_status": "degraded",
                }, ""
        else:
            return {
                "character_count": 0,
                "reason": "document_bytes_not_available",
                "__stage_status": "skipped",
            }, ""
        if not text.strip():
            return {
                "character_count": 0,
                "reason": "no_text_extracted",
                "__stage_status": "degraded" if raw_bytes is not None else "skipped",
            }, text
        return {"character_count": len(text), "extraction_method": "native_or_ocr"}, text

    def _stage_classify(self, text: str) -> tuple[dict[str, Any], str]:
        if not text.strip():
            return {
                "label": "uncategorized",
                "reason": "source_text_unavailable",
                "__stage_status": "skipped",
            }, "uncategorized"
        lowered = text.lower()
        best_label = "uncategorized"
        best_score = 0
        for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in lowered)
            if score > best_score:
                best_label = doc_type
                best_score = score
        return {"label": best_label, "score": best_score}, best_label

    def _stage_metadata(self, record: DocumentRecord, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = dict(record.metadata)
        metadata.setdefault("filename", record.filename)
        metadata.setdefault("content_type", record.content_type)
        metadata["character_count"] = len(text)
        return metadata, metadata

    def _stage_entities(self, text: str) -> tuple[dict[str, Any], list[str]]:
        if not text.strip():
            return {
                "entity_count": 0,
                "reason": "source_text_unavailable",
                "__stage_status": "skipped",
            }, []
        entities = sorted(set(_ENTITY_PATTERN.findall(text)))[:25]
        return {"entity_count": len(entities)}, entities

    def _stage_compliance(
        self, record: DocumentRecord, label: str, metadata: dict[str, Any], text: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not text.strip():
            return {
                "reason": "source_text_unavailable; compliance was not assessed",
                "__stage_status": "skipped",
            }, {"risk_score": None, "review": None}
        available_types = {label} if label != "uncategorized" else set()
        review_request = EnvironmentalReviewRequest(
            tenant_id=record.tenant_id,
            case_id=record.case_id or record.id,
            project_type=str(metadata.get("project_type", "general_review")),
            location=str(metadata.get("location", "unspecified")),
            applicant=str(metadata.get("applicant", "unspecified")),
            documents=[record.id],
        )
        citations = [
            EvidenceCitation(
                document_id=record.id,
                version=record.version,
                chunk_id="0",
                sha256=record.sha256,
                excerpt=text[:600],
            )
        ]
        review = compliance_engine.review(review_request, available_types, citations)
        stage_output = review.model_dump(mode="json")
        stage_output["reason"] = (
            "rule_based_checklist_only; authoritative regulatory-source retrieval is not configured"
        )
        stage_output["__stage_status"] = "degraded"
        return stage_output, {"risk_score": review.risk_score, "review": review}

    def _stage_risk(self, compliance_output: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
        if compliance_output.get("risk_score") is None:
            return {
                "reason": "compliance_analysis_unavailable",
                "__stage_status": "skipped",
            }, None
        risk_score = float(compliance_output["risk_score"])
        return {"risk_score": risk_score}, risk_score

    def _stage_workflow(self, record: DocumentRecord, risk_score: float | None) -> tuple[dict[str, Any], str]:
        workload = {"technical-review-pool": 4, "senior-review-pool": 1}
        # Missing evidence is routed to senior review, not assigned an invented
        # numeric risk score or treated as low risk.
        skill = "senior-review" if risk_score is None or risk_score >= 70 else "technical-review"
        assignment = assignment_engine.assign(record.case_id or record.id, skill, workload)
        return {
            "assignee": assignment.assignee,
            "due_at": assignment.due_at.isoformat(),
            "status": assignment.status.value,
        }, assignment.queue

    async def _stage_audit(
        self,
        record: DocumentRecord,
        actor: str,
        trace_id: str,
        purpose: str,
        result: DocumentProcessingResult,
        session: AsyncSession,
    ) -> dict[str, Any]:
        event = await audit_log.append(
            session,
            AuditEvent(
                tenant_id=record.tenant_id,
                actor=actor,
                action="document.pipeline_completed",
                resource_type="document",
                resource_id=str(record.id),
                purpose=purpose,
                trace_id=trace_id,
                details={
                    "classification_label": result.classification_label,
                    "risk_score": result.risk_score,
                    "entity_count": len(result.extracted_entities),
                },
            ),
        )
        return {"audit_event_id": str(event.id), "event_hash": event.event_hash}

    # -- helpers -----------------------------------------------------------

    def _timed(self, stage: PipelineStage, fn, *args) -> StageResult:
        start = time.perf_counter()
        output = fn(*args)
        duration_ms = (time.perf_counter() - start) * 1000
        stage_output = output if isinstance(output, dict) else {}
        status = stage_output.pop("__stage_status", "completed")
        return StageResult(stage=stage, status=status, output=stage_output, duration_ms=duration_ms)

    async def _timed_async(self, stage: PipelineStage, fn, *args) -> StageResult:
        start = time.perf_counter()
        output = await fn(*args)
        duration_ms = (time.perf_counter() - start) * 1000
        return StageResult(stage=stage, output=output if isinstance(output, dict) else {}, duration_ms=duration_ms)

    def _timed_with_output(self, stage: PipelineStage, fn, *args) -> tuple[StageResult, Any]:
        start = time.perf_counter()
        stage_output, value = fn(*args)
        duration_ms = (time.perf_counter() - start) * 1000
        status = stage_output.pop("__stage_status", "completed")
        return StageResult(stage=stage, status=status, output=stage_output, duration_ms=duration_ms), value


ingestion_pipeline = IngestionPipeline(ocr_engine=DocumentOcrEngine())
