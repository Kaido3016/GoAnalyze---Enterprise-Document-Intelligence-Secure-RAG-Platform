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


async def test_retrieval_trace_is_forbidden_to_non_admin(client, patched_auth, rsa_keys):
    from conftest import make_token

    private_pem, _ = rsa_keys
    token = make_token(private_pem, tenant_id="ministry-a", roles=["case-reviewer"])
    response = await client.post(
        "/v1/rag/answer?question=What%20is%20the%20policy%3F&include_retrieval_trace=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "retrieval_trace_requires_platform_admin"
