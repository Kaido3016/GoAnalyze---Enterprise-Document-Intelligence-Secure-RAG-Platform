from gov_platform.rag import GroundedRagService


def test_unavailable_result_never_claims_grounded_generation():
    finding = GroundedRagService._unavailable("generation_provider_not_configured")
    assert finding.grounded is False
    assert finding.confidence == 0.0
    assert finding.citations == []
    assert finding.finding_type == "rag_unavailable"
    assert "No verifiably grounded answer" in finding.statement


async def test_service_fails_closed_without_embedding_or_generation_provider(db_session, monkeypatch):
    import gov_platform.rag as rag_module
    from gov_platform.config import Settings

    monkeypatch.setattr(
        rag_module,
        "get_settings",
        lambda: Settings(environment="development", audit_hash_secret="test-secret"),
    )
    finding = await GroundedRagService().answer(
        "What does the document say?", "tenant-a", {"case-reviewer"}, db_session
    )
    assert finding.grounded is False
    assert finding.confidence == 0.0
    assert finding.citations == []
    assert "embedding_provider_not_configured" in finding.explanation
