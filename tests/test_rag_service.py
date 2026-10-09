from sqlalchemy import select

from gov_platform.db.models import DocumentChunkORM
from gov_platform.models import ClassificationLevel, DocumentRecord
from gov_platform.rag import GroundedRagService, split_text


def test_split_text_bounds_chunks_and_preserves_page_markers():
    text = "[Page 1]\n" + ("environmental permit evidence " * 200)
    parts = split_text(text, max_chars=500, overlap=50)
    assert len(parts) > 1
    assert all(len(part) <= 500 for part, _ in parts)
    assert parts[0][1] == 1


async def test_embedding_index_is_durable_in_database(db_session, monkeypatch):
    service = GroundedRagService()

    async def fake_embed(texts):
        return [[float(len(text)), 1.0, 0.5] for text in texts]

    monkeypatch.setattr(service, "embed", fake_embed)
    record = DocumentRecord(
        tenant_id="tenant-a",
        filename="permit.txt",
        content_type="text/plain",
        classification=ClassificationLevel.internal,
        sha256="a" * 64,
        object_uri="object://tenant-a/document",
        metadata={},
    )
    result = await service.index_document(
        record,
        "[Page 1]\nPermit evidence and water quality information. " * 40,
        db_session,
    )
    assert result["indexed"] is True
    rows = (await db_session.execute(
        select(DocumentChunkORM).where(
            DocumentChunkORM.tenant_id == "tenant-a",
            DocumentChunkORM.document_id == record.id,
        )
    )).scalars().all()
    assert len(rows) == result["chunk_count"]
    assert all(row.embedding and row.document_sha256 == "a" * 64 for row in rows)


async def test_rag_fails_closed_without_configured_providers(db_session, monkeypatch):
    from gov_platform.config import Settings
    import gov_platform.rag as rag_module

    monkeypatch.setattr(
        rag_module,
        "get_settings",
        lambda: Settings(environment="development", audit_hash_secret="test-secret"),
    )
    finding = await GroundedRagService().answer(
        "What does the permit require?", "tenant-a", {"case-reviewer"}, db_session
    )
    assert finding.grounded is False
    assert finding.citations == []
    assert finding.confidence == 0.0
    assert "embedding_provider_not_configured" in finding.explanation
