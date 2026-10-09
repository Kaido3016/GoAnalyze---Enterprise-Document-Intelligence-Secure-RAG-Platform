# Security test plan and release evidence

This plan complements automated unit/static checks. It is not a penetration-test report.

## Automated adversarial test matrix

| Area | Required negative tests |
|---|---|
| Identity | invalid signature, wrong issuer/audience, expired token, unknown kid, absent tenant claim, wrong signing algorithm |
| Tenant isolation | cross-tenant document read/download/process, RAG retrieval, case list/detail, job status, regulatory-source admin endpoints |
| Classification | protected-B access without role; attempted role escalation from client-controlled headers/attributes |
| Upload and extraction | spoofed MIME, malformed PDF/DOCX, excessive page count, huge rendered page, timeout, embedded prompt injection, archive/decompression abuse |
| RAG | forged chunk UUID, stale document version, mismatched SHA-256, invalid citation marker, cross-tenant source, malicious instructions inside retrieved text |
| LLM/provider | timeout, rate-limit response, malformed embeddings, vector dimension mismatch, missing API key, provider outage, data leakage to unapproved endpoints |
| Persistence/queue | duplicate enqueue, worker crash after claim, stale-job reclaim, retry exhaustion, DB outage, object missing after metadata commit |
| Operations | secrets in logs, CORS bypass, SSRF, request floods, container runs as non-root, backup decryption and restore integrity |

## AI evaluation contract

Run python -m evaluation.regulatory_risk_eval evaluation/regulatory_risk_golden.json after populating the fixture with expert-reviewed cases. The checked-in file is only a template; it intentionally fails the release gate. Do not fill the dataset with synthetic labels and call it legal validation.

For each benchmark case record jurisdiction, project type, source version/hash, expected retrieved source IDs, retrieved source IDs, citation IDs, citation support judgments, groundedness judgment, expert risk score, model risk score (when one exists), reviewer and review date. Freeze the dataset version and track retrieval hit rate, citation precision, unsupported grounded answers, risk MAE/RMSE/bias, subgroup errors and regression results.

The model must not produce an operational numeric risk score until the domain owner sets thresholds, confirms adequate sample sizes and representative coverage, and signs off calibration. Every decision-support output remains subject to human review.

## Evidence storage

Attach CI run URLs, container image digests, SBOMs, migration logs, staging test reports, restore-drill records and signed penetration-test/retest reports to the release record. Record the exact commit and configuration hashes. Never include credentials or sensitive production data.
