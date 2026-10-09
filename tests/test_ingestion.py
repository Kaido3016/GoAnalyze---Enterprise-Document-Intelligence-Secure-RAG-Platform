from gov_platform.ingestion import ingestion_pipeline
from gov_platform.models import ClassificationLevel, DocumentRecord, PipelineStage


def _make_record(**overrides) -> DocumentRecord:
    defaults = {
        "tenant_id": "ministry-a",
        "filename": "application_form.pdf",
        "content_type": "application/pdf",
        "classification": ClassificationLevel.internal,
        "sha256": "a" * 64,
        "object_uri": "s3://goanalyze/documents/application_form.pdf",
        "metadata": {},
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)


async def test_pipeline_runs_all_ten_stages_in_order(db_session):
    record = _make_record()

    result = await ingestion_pipeline.run(
        record=record,
        actor="test-user",
        trace_id="trace-1",
        purpose="case-review",
        session=db_session,
        raw_text="This is an Application form for a discharge permit filed by Example Applicant.",
    )

    assert result.completed is True
    stage_order = [stage.stage for stage in result.stages]
    assert stage_order == [
        PipelineStage.upload,
        PipelineStage.ocr,
        PipelineStage.classification,
        PipelineStage.metadata_extraction,
        PipelineStage.entity_extraction,
        PipelineStage.compliance_analysis,
        PipelineStage.risk_scoring,
        PipelineStage.vector_indexing,
        PipelineStage.workflow_engine,
        PipelineStage.audit_logging,
    ]


async def test_pipeline_classifies_and_scores_risk_from_text(db_session):
    record = _make_record()

    result = await ingestion_pipeline.run(
        record=record,
        actor="test-user",
        trace_id="trace-2",
        purpose="case-review",
        session=db_session,
        raw_text="Application form for site plan review.",
    )

    assert result.classification_label == "application_form"
    assert result.risk_score is not None
    assert result.workflow_queue in {"technical-review-review", "senior-review-review"}


async def test_pipeline_handles_empty_text_without_error(db_session):
    record = _make_record(filename="unlabeled.pdf")

    result = await ingestion_pipeline.run(
        record=record,
        actor="test-user",
        trace_id="trace-3",
        purpose="case-review",
        session=db_session,
        raw_text="",
    )

    assert result.completed is True
    assert result.status == "completed_with_warnings"
    assert result.classification_label == "uncategorized"
    assert result.extracted_entities == []
    assert result.risk_score is None
    stages = {stage.stage: stage for stage in result.stages}
    assert stages[PipelineStage.ocr].status == "skipped"
    assert stages[PipelineStage.compliance_analysis].status == "skipped"
    assert stages[PipelineStage.risk_scoring].status == "skipped"
    assert stages[PipelineStage.vector_indexing].status == "skipped"
    assert stages[PipelineStage.vector_indexing].output["indexed"] is False


async def test_pipeline_appends_hash_chained_audit_event(db_session):
    from gov_platform.audit import audit_log

    record = _make_record()
    before = len(await audit_log.list_events(db_session, record.tenant_id))

    await ingestion_pipeline.run(
        record=record,
        actor="test-user",
        trace_id="trace-4",
        purpose="case-review",
        session=db_session,
        raw_text="Application form",
    )

    after = await audit_log.list_events(db_session, record.tenant_id)
    assert len(after) == before + 1
    assert after[-1].event_hash is not None


async def test_audit_chain_lock_produces_correct_linear_chain(db_session):
    """Functional regression test for append_with_chain_lock's SQLite
    fallback path (correct hashing/linking with no lock). This does NOT
    test concurrency correctness -- SQLite's single-writer model means
    there is no real multi-connection race to test against here. The
    fix's actual concurrency guarantee (zero forked chains under up to 500
    concurrent PostgreSQL writers) was validated with dedicated standalone
    scripts against real PostgreSQL; see FINAL_DATABASE_AUDIT.md for that
    evidence, which cannot be reproduced in this SQLite-backed suite."""
    from gov_platform.audit import audit_log
    from gov_platform.models import AuditEvent

    tenant = "chain-lock-test-tenant"
    for i in range(5):
        await audit_log.append(
            db_session,
            AuditEvent(
                tenant_id=tenant, actor="u", action="a", resource_type="t",
                resource_id=str(i), purpose="case-review", trace_id="t",
            ),
        )

    events = await audit_log.list_events(db_session, tenant)
    assert len(events) == 5

    # exactly one root (previous_hash is None), and the rest form a single
    # linear chain with no forks/duplicates
    roots = [e for e in events if e.previous_hash is None]
    assert len(roots) == 1

    event_hashes = [e.event_hash for e in events]
    assert len(event_hashes) == len(set(event_hashes))

    previous_hashes = [e.previous_hash for e in events if e.previous_hash is not None]
    assert len(previous_hashes) == len(set(previous_hashes))  # no fork: no two events share a previous_hash
