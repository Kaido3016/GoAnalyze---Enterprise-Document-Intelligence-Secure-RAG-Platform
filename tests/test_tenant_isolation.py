from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from gov_platform import security
from gov_platform.config import Settings

TEST_ISSUER = "https://keycloak.test/realms/goanalyze"
TEST_AUDIENCE = "goanalyze-api"
KEY_ID = "test-signing-key-1"


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def rsa_keys():
    private_pem, public_pem = _generate_rsa_keypair()
    public_key = serialization.load_pem_public_key(public_pem)
    public_jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    public_jwk["kid"] = KEY_ID
    public_jwk["alg"] = "RS256"
    return private_pem, public_jwk


@pytest.fixture(autouse=True)
def patched_auth(monkeypatch, rsa_keys):
    _, public_jwk = rsa_keys
    test_settings = Settings(
        keycloak_issuer=TEST_ISSUER,
        keycloak_audience=TEST_AUDIENCE,
        environment="development",
        allow_insecure_dev_auth=False,
        audit_hash_secret="test-secret",
    )
    monkeypatch.setattr(security, "get_settings", lambda: test_settings)

    async def fake_get_jwks(jwks_uri, *, force_refresh=False):
        return [public_jwk]

    monkeypatch.setattr(security, "_get_jwks", fake_get_jwks)


def _token(private_pem, tenant_id, roles, sub="user-1"):
    now = datetime.now(UTC)
    claims = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "tenant_id": tenant_id,
        "roles": roles,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KEY_ID})


async def test_documents_endpoint_rejects_unauthenticated_requests(client):
    response = await client.post(
        "/v1/documents",
        json={
            "tenant_id": "ministry-a",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "object_uri": "s3://x/a.pdf",
        },
    )
    assert response.status_code == 401


async def test_documents_endpoint_rejects_forged_legacy_token(client):
    response = await client.post(
        "/v1/documents",
        headers={"Authorization": "Bearer tenant:ministry-a:platform-admin"},
        json={
            "tenant_id": "ministry-a",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "object_uri": "s3://x/a.pdf",
        },
    )
    assert response.status_code == 401


async def test_valid_token_can_ingest_own_tenant_document(client, rsa_keys):
    private_pem, _ = rsa_keys
    token = _token(private_pem, "ministry-a", ["case-reviewer"])

    response = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tenant_id": "ministry-a",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "object_uri": "s3://x/a.pdf",
        },
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "ministry-a"


async def test_cannot_ingest_document_for_another_tenant(client, rsa_keys):
    private_pem, _ = rsa_keys
    token = _token(private_pem, "ministry-a", ["case-reviewer"])

    response = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tenant_id": "ministry-b",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "object_uri": "s3://x/a.pdf",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant_mismatch"


async def test_rag_answer_requires_authentication(client):
    response = await client.post("/v1/rag/answer", params={"question": "test"}, json=[])
    assert response.status_code == 401


async def test_rag_answer_ignores_caller_supplied_cross_tenant_citations(client, rsa_keys):
    private_pem, _ = rsa_keys
    owner_token = _token(private_pem, "ministry-a", ["case-reviewer"])
    attacker_token = _token(private_pem, "ministry-b", ["case-reviewer"], sub="attacker-1")

    ingest = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "tenant_id": "ministry-a",
            "filename": "secret.pdf",
            "content_type": "application/pdf",
            "sha256": "b" * 64,
            "object_uri": "s3://x/secret.pdf",
        },
    )
    assert ingest.status_code == 200
    document_id = ingest.json()["id"]

    response = await client.post(
        "/v1/rag/answer",
        params={"question": "What does this say?"},
        headers={"Authorization": f"Bearer {attacker_token}"},
        json=[
            {
                "document_id": document_id,
                "version": 1,
                "chunk_id": "0",
                "sha256": "b" * 64,
                "excerpt": "forged excerpt claiming to be from ministry-a's document",
            }
        ],
    )
    assert response.status_code == 200
    assert response.json()["grounded"] is False
    assert response.json()["citations"] == []
    assert "forged excerpt" not in response.text


async def test_rag_answer_uses_retrieved_evidence_not_caller_supplied_citations(client, rsa_keys):
    private_pem, _ = rsa_keys
    token = _token(private_pem, "ministry-a", ["case-reviewer"])

    ingest = await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tenant_id": "ministry-a",
            "filename": "public-notice.pdf",
            "content_type": "application/pdf",
            "sha256": "c" * 64,
            "object_uri": "s3://x/public-notice.pdf",
        },
    )
    document_id = ingest.json()["id"]

    response = await client.post(
        "/v1/rag/answer",
        params={"question": "What is this about?"},
        headers={"Authorization": f"Bearer {token}"},
        json=[
            {
                "document_id": document_id,
                "version": 1,
                "chunk_id": "0",
                "sha256": "c" * 64,
                "excerpt": "This notice concerns a public consultation period.",
            }
        ],
    )
    assert response.status_code == 200
    assert response.json()["grounded"] is False
    assert response.json()["citations"] == []


async def test_audit_endpoint_only_returns_own_tenant_events(client, rsa_keys):
    private_pem, _ = rsa_keys
    token_a = _token(private_pem, "ministry-a", ["case-reviewer"])
    token_b = _token(private_pem, "ministry-b", ["case-reviewer"])

    await client.post(
        "/v1/documents",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "tenant_id": "ministry-a",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "sha256": "d" * 64,
            "object_uri": "s3://x/a.pdf",
        },
    )

    response_b = await client.get("/v1/audit", headers={"Authorization": f"Bearer {token_b}"})
    assert response_b.status_code == 200
    assert response_b.json()["items"] == []
    assert response_b.json()["total"] == 0

    response_a = await client.get("/v1/audit", headers={"Authorization": f"Bearer {token_a}"})
    assert response_a.status_code == 200
    assert len(response_a.json()["items"]) >= 1
    assert response_a.json()["total"] >= 1
