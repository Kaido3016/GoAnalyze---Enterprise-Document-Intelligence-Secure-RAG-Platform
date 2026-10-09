import uuid

from tests.conftest import make_token


async def test_case_create_list_detail_are_tenant_scoped(client, patched_auth, rsa_keys):
    private_pem, _ = rsa_keys
    token_a = make_token(private_pem, tenant_id="ministry-a", roles=["case-manager"])
    token_b = make_token(private_pem, tenant_id="ministry-b", roles=["case-manager"])
    created = await client.post(
        "/v1/cases",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "title": "North watershed permit",
            "project_type": "industrial_discharge",
            "location": "North watershed",
            "applicant": "Example applicant",
            "attributes": {},
        },
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    listing = await client.get("/v1/cases", headers={"Authorization": f"Bearer {token_a}"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    detail = await client.get(f"/v1/cases/{case_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert detail.status_code == 200
    assert detail.json()["title"] == "North watershed permit"
    cross_tenant = await client.get(f"/v1/cases/{case_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert cross_tenant.status_code == 404


async def test_async_document_processing_job_is_durable_and_tenant_scoped(
    client, patched_auth, rsa_keys
):
    private_pem, _ = rsa_keys
    token_a = make_token(private_pem, tenant_id="ministry-a", roles=["case-manager"])
    token_b = make_token(private_pem, tenant_id="ministry-b", roles=["case-manager"])
    response = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "tenant_id": "ministry-a",
            "filename": "permit.txt",
            "content_type": "text/plain",
            "sha256": "a" * 64,
            "object_uri": "ignored://client-value",
        },
    )
    assert response.status_code == 200
    document_id = response.json()["id"]
    queued = await client.post(
        f"/v1/documents/{document_id}/process-async",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert queued.status_code == 202
    job_id = queued.json()["id"]
    status = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    cross_tenant = await client.get(
        f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant.status_code == 404
