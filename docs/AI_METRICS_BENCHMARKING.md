# GoAnalyze AI metrics benchmark suite

This suite creates reproducible JSON reports for the eight AI-engineering metrics requested for the project. It deliberately separates **measured outputs**, **label-dependent scores**, and **estimates**. It does not manufacture benchmark labels or business results.

## 1. Prepare a reviewed golden set

Copy `evaluation/metrics/golden_dataset.template.json` to `evaluation/metrics/golden_dataset.json`. Populate it with representative, non-sensitive questions from the target workflow. Have a domain reviewer freeze the expected answer criteria and expected evidence document IDs before running the benchmark.

Example case:

```json
{
  "id": "policy-001",
  "question": "What evidence does the approved policy require?",
  "expected_answer_contains": ["required phrase reviewed by the domain owner"],
  "expected_document_ids": ["UUID-OF-EXPECTED-DOCUMENT"],
  "expected_grounded": true,
  "must_abstain": false
}
```

Use actual UUID values and exact, reviewer-approved answer criteria. A substring check is a weak smoke-test oracle, not semantic equivalence. For a defensible model-quality score, add a reviewer-adjudicated semantic label per case and record reviewer, date, dataset version, and adjudication notes. Keep an untouched holdout set separate from development examples.

## 2. Run the RAG / model benchmark

The API must be running with a configured embedding provider, generation provider, indexed test documents, and an authorized test identity.

PowerShell:

```powershell
$env:GOANALYZE_BASE_URL = "http://localhost:8080"
$env:GOANALYZE_BEARER_TOKEN = "<short-lived-test-token>"
python scripts/metrics/benchmark_rag.py --dataset evaluation/metrics/golden_dataset.json
```

Optional cost estimate (use the exact provider/model price for the run):

```powershell
python scripts/metrics/benchmark_rag.py --dataset evaluation/metrics/golden_dataset.json --input-usd-per-1m-tokens 0.15 --output-usd-per-1m-tokens 0.60
```

The script writes `metrics/reports/rag-benchmark.json` and reports:

| Requested metric | Measurement |
|---|---|
| Model quality | Pass rate against reviewed expected answer terms / expected groundedness labels. This is a proxy until semantic human adjudication exists. |
| RAG retrieval quality | Recall/precision of expected document IDs among documents cited in the answer. This is a citation-evidence proxy, **not hidden top-K retrieval Recall@K**. |
| End-to-end task success | Cases satisfying the configured answer, grounding, and expected-evidence checks. |
| Latency | p50 / p95 / p99 and mean request latency. |
| Cost efficiency | Approximate token-cost estimate only when pricing is supplied. Token counts are estimated from characters; this is not provider billing data. |
| Reliability | HTTP success rate and request errors during the run. |
| Scale / throughput | Requests per second at the configured concurrency. Use the dedicated load test for controlled concurrency sweeps. |

The endpoint returns citations selected by the generated answer, not the full retriever candidate list. Do not relabel citation recall as retriever Recall@K. A future retrieval instrumentation change should expose ranked chunk IDs and scores to a protected benchmark-only trace or offline evaluator.

## 3. Run a controlled load test

Run only against a dedicated staging/test environment and a non-sensitive representative question:

```powershell
python scripts/metrics/load_test_rag.py --question "What does the test policy require?" --requests 200 --concurrency 10
```

The report includes throughput, success rate, p50/p95/p99/max latency, grounded-response rate, and error classes. Repeat at concurrency 1, 5, 10, 25, 50 (within provider quotas), then perform a soak test. Record machine size, database size, provider/model, region, warm/cold cache, and rate limits with each run. The current RAG implementation ranks tenant-authorized chunks in application memory; this is a benchmark of the current architecture, not evidence of large-corpus ANN scale.

## 4. Measure real business impact

Collect paired timings for the same workflow, task definition, and comparable task mix. Create a CSV with these columns:

```csv
task_id,baseline_seconds,assisted_seconds
case-001,900,420
case-002,780,390
```

The values above are illustrative only; replace them with observed timings. Then run:

```powershell
python scripts/metrics/business_impact.py --csv pilot_timings.csv --tasks-per-month 500 --loaded-hourly-cost 55
```

The report calculates average time saved per task, percentage time reduction, extrapolated hours saved per month/year, and optional labor value in CAD. Preserve sample size, observation dates, operator/task mix, and methodology. Do not present extrapolation as realized savings without a measured pilot.

## 5. Metric governance and CV use

- Keep benchmark data non-sensitive and tenant-authorized. Never commit bearer tokens, provider keys, or customer documents.
- Freeze and version the dataset; separate development and independent holdout cases.
- Report denominators and missing labels. A metric with no reviewed cases must be `null`, not 0% or 100%.
- Store each JSON report with the commit SHA, environment, provider/model, embedding model, corpus snapshot, and configuration.
- Run the same dataset after changes and compare reports; investigate regressions rather than selecting only favorable runs.
- For a CV, state the exact measured setup and sample size. Do not claim production deployment, business ROI, semantic accuracy, or capacity from synthetic data, smoke tests, or a local benchmark.

## Metric maturity

| Metric | Initial script evidence | Additional evidence needed for a strong claim |
|---|---|---|
| Model quality | reviewed term / grounding checks | blind semantic adjudication, multiple reviewers, inter-rater agreement |
| Retrieval | cited-document precision/recall proxy | instrumented top-K chunk IDs, Recall@K, MRR/nDCG, authorization leakage tests |
| End-to-end | answer + grounding + citation acceptance | complete user workflow with success criteria and failure taxonomy |
| Latency | observed API percentiles | repeated runs, production-like data and p95/p99 SLOs |
| Cost | optional rough estimate | provider-reported token usage and invoice reconciliation |
| Reliability | HTTP success/error rate | long-running soak, dependency failure, retry and recovery tests |
| Scale | concurrent API throughput | controlled load/soak/failover tests with documented hardware and bottlenecks |
| Business impact | paired task-time extrapolation | representative pilot, baseline controls, verified volume and stakeholder sign-off |
