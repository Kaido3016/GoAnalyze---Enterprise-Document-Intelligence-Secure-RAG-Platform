import uuid

from tests.conftest import make_token


async def _ingest(client, token: str, tenant_id: str, filename: str, digest: str) -> str:
    response = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tenant_id": tenant_id,
            "filename": filename,
            "content_type": "application/pdf",
            "sha256": digest,
            "object_uri": "pending://test/object",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object_uri"] == f"object://{tenant_id}/{payload['id']}"
    return payload["id"]


async def test_document_list_is_tenant_scoped(client, patched_auth, rsa_keys):
    private_pem, _ = rsa_keys
    token_a = make_token(private_pem, tenant_id="ministry-a")
    token_b = make_token(private_pem, tenant_id="ministry-b")
    await _ingest(client, token_a, "ministry-a", "a.pdf", "a" * 64)
    await _ingest(client, token_b, "ministry-b", "b.pdf", "b" * 64)

    response = await client.get(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["filename"] for item in payload["items"]] == ["b.pdf"]


async def test_document_detail_rejects_cross_tenant_access(client, patched_auth, rsa_keys):
    private_pem, _ = rsa_keys
    token_a = make_token(private_pem, tenant_id="ministry-a")
    token_b = make_token(private_pem, tenant_id="ministry-b")
    document_id = await _ingest(client, token_a, "ministry-a", "private.pdf", "c" * 64)

    response = await client.get(
        f"/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 403


async def test_environmental_review_rejects_cross_tenant_document(client, patched_auth, rsa_keys):
    private_pem, _ = rsa_keys
    token_a = make_token(private_pem, tenant_id="ministry-a")
    token_b = make_token(private_pem, tenant_id="ministry-b")
    document_id = await _ingest(client, token_b, "ministry-b", "other-tenant.pdf", "d" * 64)

    response = await client.post(
        "/v1/environmental-reviews",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "tenant_id": "ministry-a",
            "case_id": str(uuid.uuid4()),
            "project_type": "industrial",
            "location": "Example location",
            "applicant": "Example applicant",
            "documents": [document_id],
            "attributes": {},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "review_document_tenant_mismatch"
