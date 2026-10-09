# Audit remediation — code changes and remaining gates

This document records the remediation branch changes. It does not claim that the platform is production-ready or that tests have passed before CI runs.

## Corrected in this branch

- **Grounded answers fail closed.** The current repository has no configured generation provider or retrieval-backed chunk store. The API no longer concatenates caller-supplied excerpts into an apparent AI answer or assigns confidence based on citation count. It reports generation as unavailable with zero confidence and no grounded claim.
- **Citation integrity checks.** The RAG endpoint checks each supplied citation's document version and SHA-256 against the persisted document record, in addition to tenant/classification authorization.
- **No false vector-index success.** The ingestion pipeline reports vector indexing as skipped until an embedding model and vector-store write path are configured.
- **Honest pipeline status.** Empty/unavailable source text marks OCR, classification, entity extraction, compliance analysis, and risk scoring as skipped as appropriate. The API distinguishes completed orchestration from completed_with_warnings; missing evidence is routed to senior review without inventing a numeric risk score.
- **Storage fails closed.** MinIO initialization/connectivity failures no longer silently switch production writes to process-local memory. An in-memory fallback is permitted only in development when GOV_ALLOW_IN_MEMORY_STORAGE_FALLBACK=true; otherwise the API returns HTTP 503.
- **Document API foundations.** Added tenant-scoped paginated GET /v1/documents and authorized GET /v1/documents/{document_id} endpoints.
- **Environmental-review isolation.** Reviews reject missing documents and any document whose tenant does not match the review tenant; classification/purpose authorization is checked before evidence is used.
- **No filename-as-evidence compliance claims.** Environmental review no longer fabricates citations from filenames. Rule-based checklists and regulation mappings are explicitly ungrounded until authoritative regulatory sources and verified extracted text are connected; pipeline compliance is marked degraded.
- **Server-controlled object URI.** Ingestion replaces the client-provided URI with a server-derived internal object key.
- **Bounded request reading.** Upload size is enforced as chunks arrive rather than after Request.body() has already buffered an arbitrarily large request.
- **Setup response honesty.** /v1/setup no longer claims requested external services were validated. It explicitly warns that the endpoint does not persist settings or check connectivity.
- **Regression tests added** for fail-closed RAG, storage fallback policy, tenant-scoped document reads, cross-tenant environmental-review rejection, and empty-document pipeline statuses.

## Still requires real providers or environment-level work

These items cannot honestly be marked fixed by source changes alone:

1. **Real OCR and document extraction:** NullOcrEngine is still the default. Configure and integration-test PDF/DOCX/TXT extraction and OCR for scanned PDFs, including limits and malformed-file handling.
2. **Real semantic RAG:** implement/configure chunking, embeddings, durable vector indexing, tenant/classification-filtered retrieval, a generation provider, prompt-injection defenses, and citation-grounded output validation. The API now says this capability is unavailable rather than faking it.
3. **Compliance and risk validity:** keyword classification and the domain engine still need representative labeled evaluation, authoritative regulatory-source provenance, calibration, and domain/legal review. Do not use unvalidated scores for consequential decisions.
4. **Case APIs and workflow persistence:** case listing/detail and aggregate processing/risk analytics require a durable case/workflow model and frontend contract tests. Assignment remains a separate action endpoint.
5. **Production storage and uploads:** provision durable MinIO/S3 and test outage/recovery. The current storage protocol still accepts in-memory bytes; true streaming-to-object-store requires a streaming/multipart storage interface.
6. **Identity and infrastructure:** provision Keycloak realm/client or the chosen IdP, production secrets, TLS/network policy, and test the deployment topology.
7. **Reliability:** reconcile object storage and database writes, add cleanup/compensation for partial failures, and use an asynchronous queue for long-running document processing.
8. **Security and operations:** independent penetration testing, backup/restore and disaster-recovery exercises, retention/deletion verification, externally anchored audit evidence, load tests, and target-environment acceptance remain required.
9. **Frontend dependency security:** current CI npm audit still fails on 10 existing advisories (9 high, 1 critical), including Next.js, sharp, and source-map-js. Upgrade to patched versions and regenerate/commit package-lock.json as a reviewed dependency change before merging; do not bypass the audit gate.

## Verification

The GitHub Actions CI workflow is expected to run against this branch through the pull request. Do not treat a successful static/unit-test CI run as proof of live OCR, LLM, vector-store, Keycloak, MinIO, Kubernetes, or government-environment acceptance.
