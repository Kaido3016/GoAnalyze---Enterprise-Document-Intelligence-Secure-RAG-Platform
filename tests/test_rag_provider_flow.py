import re

from sqlalchemy.ext.asyncio import AsyncSession

import gov_platform.rag as rag_module
from gov_platform.config import Settings
from gov_platform.db.models import DocumentChunkORM, DocumentORM
from gov_platform.rag import GroundedRagService


async def _seed_chunk(session: AsyncSession, tenant_id: str, text: str, digest: str):
    document = DocumentORM(
        tenant_id=tenant_id,
        filename="permit.txt",
        content_type="text/plain",
        classification="internal",
        sha256=digest,
        object_uri=f"object://{tenant_id}/permit",
        version=1,
    )
    session.add(document)
    await session.flush()
    chunk = DocumentChunkORM(
        tenant_id=tenant_id,
        document_id=document.id,
        document_version=1,
        document_sha256=digest,
        classification="internal",
        chunk_index=0,
        page=1,
        content=text,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="test-embedding",
    )
    session.add(chunk)
    await session.flush()
    return document, chunk


def _settings():
    return Settings(
        environment="development",
        audit_hash_secret="test-secret",
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="test-embedding-key",
        llm_base_url="https://llm.example/v1",
        llm_api_key="test-llm-key",
        embedding_model="test-embedding",
        rag_min_similarity=0.15,
    )


async def test_answer_retrieves_only_current_tenant_chunks_and_validates_citation(db_session, monkeypatch):
    monkeypatch.setattr(rag_module, "get_settings", _settings)
    service = GroundedRagService()
    own_doc, own_chunk = await _seed_chunk(db_session, "tenant-a", "Water discharge permit terms.", "a" * 64)
    await _seed_chunk(db_session, "tenant-b", "CROSS TENANT SECRET.", "b" * 64)
    await db_session.commit()

    async def fake_embed(_texts):
        return [[1.0, 0.0, 0.0]]

    seen_context = {}

    async def fake_post(_base_url, _api_key, path, payload):
        assert path == "/chat/completions"
        context = payload["messages"][1]["content"]
        seen_context["content"] = context
        match = re.search(r"\[chunk:([0-9a-f-]{36})\]", context)
        assert match
        return {"choices": [{"message": {"content": f"The permit contains water discharge terms [chunk:{match.group(1)}]"}}]}

    monkeypatch.setattr(service, "embed", fake_embed)
    monkeypatch.setattr(service, "_post", fake_post)
    finding = await service.answer("Summarize the permit", "tenant-a", {"case-reviewer"}, db_session)
    assert finding.grounded is True
    assert finding.citations[0].document_id == own_doc.id
    assert finding.citations[0].chunk_id == str(own_chunk.id)
    assert "CROSS TENANT SECRET" not in seen_context["content"]


async def test_answer_rejects_forged_model_citation(db_session, monkeypatch):
    monkeypatch.setattr(rag_module, "get_settings", _settings)
    service = GroundedRagService()
    await _seed_chunk(db_session, "tenant-a", "Current evidence.", "c" * 64)
    await db_session.commit()

    async def fake_embed(_texts):
        return [[1.0, 0.0, 0.0]]

    async def fake_post(_base_url, _api_key, path, _payload):
        assert path == "/chat/completions"
        return {"choices": [{"message": {"content": "Unsupported claim [chunk:00000000-0000-0000-0000-000000000000]"}}]}

    monkeypatch.setattr(service, "embed", fake_embed)
    monkeypatch.setattr(service, "_post", fake_post)
    finding = await service.answer("Question", "tenant-a", {"case-reviewer"}, db_session)
    assert finding.grounded is False
    assert finding.citations == []
    assert "invalid_chunk_citations" in finding.explanation


async def test_embedding_provider_response_is_sorted_and_validated(monkeypatch):
    monkeypatch.setattr(rag_module, "get_settings", _settings)
    service = GroundedRagService()

    async def fake_post(_base_url, _api_key, path, payload):
        assert path == "/embeddings"
        assert payload["model"] == "test-embedding"
        return {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }

    monkeypatch.setattr(service, "_post", fake_post)
    vectors = await service.embed(["first", "second"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
