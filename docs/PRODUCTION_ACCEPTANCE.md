# Production identity, security, backup and deployment acceptance

**Status: NOT ACCEPTED until every release gate below is evidenced in the target environment.** The repository cannot perform an independent penetration test or a real disaster-recovery drill without the operator's authorization, isolated target, identity-provider administration, and production-equivalent infrastructure.

## Identity provider setup (Keycloak)

1. Review keycloak/goanalyze-realm.json; replace the example frontend host with the exact production origin and redirect URIs before import.
2. Import the realm using the approved Keycloak release and a controlled administrative process. Do not use start-dev in production.
3. Use TLS end-to-end or a trusted TLS-terminating ingress; set the public realm issuer URL to the exact HTTPS URL that appears in tokens. The API must use the same issuer and the goanalyze-api audience.
4. Store the Keycloak bootstrap admin secret and API credentials in the organization's secret manager. Rotate/remove bootstrap credentials after provisioning.
5. Assign tenant_id and ministry as server-controlled user attributes. Do not let users self-edit these attributes. Grant realm roles only through an approved identity-governance process.
6. Replace frontend redirect URIs and origins with exact allowlisted hosts; do not use wildcard production origins. Confirm PKCE S256 is enabled.
7. Test issuer, audience, expiry, unknown signing key, key rotation, missing tenant claim, role escalation, disabled user, logout/revocation policy, and cross-tenant access. Verify the API fails closed when JWKS is unavailable and no trusted cached key exists.
8. Ensure production GOV_ALLOW_INSECURE_DEV_AUTH=false, a strong unique GOV_AUDIT_HASH_SECRET, HTTPS provider URLs, restricted CORS origins, and least-privilege service credentials.

## Official regulatory-source ingestion

1. Apply database migrations with alembic upgrade head.
2. Configure GOV_EMBEDDING_BASE_URL, GOV_EMBEDDING_API_KEY, and GOV_EMBEDDING_MODEL in the secret manager; the endpoint must implement the OpenAI-compatible /embeddings contract.
3. Seed the fixed official-source catalog with python -m gov_platform.regulatory_sources seed.
4. Fetch and embed the allowlisted official pages with python -m gov_platform.regulatory_sources sync. The command verifies HTTPS and redirect host allowlists, stores a content SHA-256, captures an official consolidation date when present, and leaves every source in fetched_pending_review.
5. A legal/domain reviewer must compare the stored content with the current official source, confirm jurisdiction and applicability, and then an authorized platform-admin can approve the exact version through POST /v1/regulatory-sources/{source_id}/approve with source_version and a reviewer_note of at least 10 characters.
6. A changed source hash resets it to pending review; retrieval only uses approved chunks whose hash still matches the current source record.
7. Do not treat the five initial official sources as a complete regulatory corpus. Add jurisdiction-specific regulations and guidance only after source-authority, versioning, applicability and licensing review.

## Database and object-storage backup / restore

- Encrypt backup artifacts with an organization-managed age recipient or equivalent KMS-managed encryption. Store private decryption identities separately from backup media.
- Quiesce writes or use a coordinated consistent snapshot. PostgreSQL and object storage are separate systems; an uncoordinated backup may capture different points in time.
- Run bash scripts/backup.sh from a hardened runner with restricted access. Copy encrypted artifacts and checksums to an independent region/account with immutable retention.
- Run bash scripts/restore-drill.sh only against a dedicated empty restore database and bucket ending in -restore-drill. Never point the drill at production.
- After restore, run Alembic migration checks, tenant-scoped row counts, object counts and SHA-256 spot checks, document download/decryption, search/RAG smoke tests, audit-chain verification, and application health checks.
- Record measured recovery point objective (RPO), recovery time objective (RTO), missing objects, operator, date, and remediation. Repeat quarterly and after material schema/storage changes.

## Independent security assessment

Engage an independent qualified security team; do not describe repository CI as a penetration test. Provide the assessor with an approved scope, written authorization, isolated test tenant/data, test window, emergency contacts, and a staging environment equivalent to production.

Minimum scope:
- OIDC/JWKS validation, tenant isolation, RBAC/ABAC, protected-B authorization, IDOR, session/token handling and rate limits.
- Upload/parser abuse, PDF/OCR resource exhaustion, MIME spoofing, malware, prompt injection and poisoned retrieved content.
- SQL injection, SSRF, CORS/CSP, security headers, secret exposure, dependency/supply-chain risk, container privileges and network segmentation.
- Object-storage bucket policies, encryption, signed access, backups, restore controls, audit-log integrity and privileged administrator abuse.
- LLM data exfiltration, unauthorized tool execution, citation forgery, cross-tenant retrieval and refusal behavior.

Deliverables: signed scope, methodology, findings with severity and reproducible evidence, remediation tickets, retest report, and risk-owner sign-off for accepted residual findings.

## Deployment acceptance gates

- [ ] alembic upgrade head and alembic check pass against a production-like PostgreSQL version.
- [ ] API and worker images build from pinned dependencies; image/SBOM scans and signature/provenance checks pass.
- [ ] Frontend npm ci, npm run lint, npm run typecheck, npm run build, and npm audit --audit-level=high pass.
- [ ] Backend Ruff, mypy, unit tests, PostgreSQL integration tests, cross-tenant authorization tests and migration tests pass.
- [ ] OCR tests cover selectable PDFs, scanned PDFs, rotated pages, multiple pages, DOCX, images, malformed files, page-count caps, timeouts and oversized documents.
- [ ] RAG uses configured provider endpoints and keys, tenant/classification filters, current-version hashes, citation validation, and a reviewed benchmark that meets domain-approved thresholds.
- [ ] Regulatory sources have verified hashes/version dates, human reviewer approval, legal applicability review, and a regression/evaluation set for each supported jurisdiction.
- [ ] Case/job APIs, worker retry behavior, dead-letter handling, idempotency, monitoring and queue-depth alerts are tested.
- [ ] TLS, secret rotation, encryption at rest/in transit, retention/deletion, disaster recovery and least privilege are validated.
- [ ] Load, soak, failure-injection, failover and rollback exercises pass with measured SLOs.
- [ ] Independent penetration test and remediation retest are complete.
- [ ] Business/domain/legal owners approve the remaining risks and production go-live.

## Current limitations that must remain visible

The code now supports a configurable OpenAI-compatible embedding and chat endpoint, persisted chunks, and a durable PostgreSQL job queue. Vector similarity is currently calculated in application memory over tenant-filtered persisted chunks; it is suitable for modest test corpora, not a scale claim. Move to pgvector/HNSW or OpenSearch k-NN before large production corpora and benchmark it.

Risk scoring is intentionally unavailable until an expert-labeled dataset and validated calibration model exist. A checklist or LLM output is not a legal decision. Regulatory source ingestion leaves content in fetched_pending_review; only an authorized platform administrator can approve a verified source version for retrieval.

No independent penetration test, live production identity deployment, or real backup/restore drill is claimed by this branch.
