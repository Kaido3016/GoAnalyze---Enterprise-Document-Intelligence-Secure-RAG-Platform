from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gov_platform.db.models import RegulatoryChunkORM, RegulatorySourceORM
from tests.conftest import make_token


async def test_regulatory_sources_require_platform_admin(client, rsa_keys):
    private_pem, _ = rsa_keys
    token = make_token(private_pem, tenant_id="ministry-a", roles=["case-reviewer"])
    response = await client.get("/v1/regulatory-sources", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_platform_admin_can_approve_reviewed_official_source(
    client, db_engine, rsa_keys
):
    private_pem, _ = rsa_keys
    token = make_token(private_pem, tenant_id="platform", roles=["platform-admin"])
    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    source_id = uuid4()
    digest = "d" * 64
    async with maker() as session:
        source = RegulatorySourceORM(
            id=source_id,
            jurisdiction="QC",
            title="Environment Quality Act",
            official_url="https://www.legisquebec.gouv.qc.ca/en/document/cs/Q-2",
            authority_domain="www.legisquebec.gouv.qc.ca",
            status="fetched_pending_review",
            content_sha256=digest,
            content_text="Verified official text",
            last_verified_at=datetime.now(UTC),
        )
        session.add(source)
        await session.flush()
        session.add(
            RegulatoryChunkORM(
                source_id=source_id,
                chunk_index=0,
                content="Verified official text",
                embedding=[1.0, 0.0],
                embedding_model="test-model",
                source_sha256=digest,
            )
        )
        await session.commit()

    listed = await client.get("/v1/regulatory-sources", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "fetched_pending_review"

    approved = await client.post(
        f"/v1/regulatory-sources/{source_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_version": "Consolidated to 2026-09-01",
            "reviewer_note": "Compared with the official legislation page and verified this version.",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["content_sha256"] == digest
