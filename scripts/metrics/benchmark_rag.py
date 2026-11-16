#!/usr/bin/env python3
"""Black-box RAG evaluation for GoAnalyze.

Uses only the Python standard library. Labels must come from a reviewed,
frozen evaluation set; this script never invents ground truth.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((p / 100) * len(ordered)) - 1)
    return round(ordered[index], 3)


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("dataset must be a non-empty JSON array")
    seen: set[str] = set()
    for case in payload:
        if not isinstance(case, dict):
            raise ValueError("each dataset entry must be an object")
        case_id = str(case.get("id", "")).strip()
        question = str(case.get("question", "")).strip()
        if not case_id or not question:
            raise ValueError("every case requires non-empty id and question")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        if not any(k in case for k in ("expected_answer_contains", "expected_document_ids", "expected_grounded", "must_abstain")):
            raise ValueError(f"{case_id}: add at least one reviewed expectation")
    return payload


def request_answer(base_url: str, token: str, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    query = urllib.parse.urlencode({"question": case["question"]})
    url = f"{base_url.rstrip('/')}/v1/rag/answer?{query}"
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Purpose": "case-review",
            "Content-Length": "0",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {"case": case, "body": body, "latency_ms": elapsed_ms, "error": None}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"case": case, "body": {}, "latency_ms": elapsed_ms, "error": f"{type(exc).__name__}: {exc}"}


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    case = result["case"]
    body = result["body"]
    statement = str(body.get("statement", ""))
    explanation = str(body.get("explanation", ""))
    answer_text = f"{statement}\n{explanation}".casefold()
    citations = body.get("citations") or []
    cited_docs = {str(c.get("document_id")) for c in citations if c.get("document_id")}
    expected_docs = {str(x) for x in case.get("expected_document_ids", [])}
    expected_terms = [str(x).casefold() for x in case.get("expected_answer_contains", [])]
    missing_terms = [term for term in expected_terms if term not in answer_text]
    grounded_expected = case.get("expected_grounded")
    must_abstain = bool(case.get("must_abstain", False))
    grounded = bool(body.get("grounded", False))
    model_checks: list[bool] = []
    if expected_terms:
        model_checks.append(not missing_terms)
    if grounded_expected is not None:
        model_checks.append(grounded == bool(grounded_expected))
    if must_abstain:
        model_checks.append(not grounded)
    model_pass = all(model_checks) if model_checks else None

    retrieval_recall = (
        len(expected_docs & cited_docs) / len(expected_docs) if expected_docs else None
    )
    retrieval_precision = (
        len(expected_docs & cited_docs) / len(cited_docs) if expected_docs and cited_docs else
        (1.0 if expected_docs and not cited_docs and not expected_docs else None)
    )
    retrieval_hit = bool(expected_docs & cited_docs) if expected_docs else None
    end_to_end = None
    if model_pass is not None and expected_docs:
        end_to_end = model_pass and retrieval_hit and grounded
    elif model_pass is not None:
        end_to_end = model_pass and (grounded or must_abstain)

    return {
        "id": case["id"],
        "success_http": result["error"] is None,
        "latency_ms": round(result["latency_ms"], 3),
        "error": result["error"],
        "grounded": grounded,
        "citation_count": len(citations),
        "cited_document_ids": sorted(cited_docs),
        "expected_document_ids": sorted(expected_docs),
        "model_quality_pass": model_pass,
        "missing_expected_terms": missing_terms,
        "retrieval_citation_recall": retrieval_recall,
        "retrieval_citation_precision": retrieval_precision,
        "retrieval_hit": retrieval_hit,
        "end_to_end_success": end_to_end,
        "answer_chars": len(statement),
        "response_chars": len(json.dumps(body, ensure_ascii=False)),
    }


def ratio(values: list[bool]) -> float | None:
    return round(sum(values) / len(values) * 100, 2) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("GOANALYZE_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--token", default=os.getenv("GOANALYZE_BEARER_TOKEN"))
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/metrics/golden_dataset.json"))
    parser.add_argument("--output", type=Path, default=Path("metrics/reports/rag-benchmark.json"))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--input-usd-per-1m-tokens", type=float, default=None)
    parser.add_argument("--output-usd-per-1m-tokens", type=float, default=None)
    args = parser.parse_args()

    if not args.token:
        parser.error("set GOANALYZE_BEARER_TOKEN or pass --token")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    cases = load_cases(args.dataset)
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        raw = list(pool.map(lambda c: request_answer(args.base_url, args.token, c, args.timeout), cases))
    elapsed = time.perf_counter() - started
    rows = [evaluate(item) for item in raw]

    latencies = [r["latency_ms"] for r in rows]
    successful = [r for r in rows if r["success_http"]]
    model_values = [r["model_quality_pass"] for r in rows if r["model_quality_pass"] is not None]
    retrieval_recalls = [r["retrieval_citation_recall"] for r in rows if r["retrieval_citation_recall"] is not None]
    retrieval_precisions = [r["retrieval_citation_precision"] for r in rows if r["retrieval_citation_precision"] is not None]
    e2e_values = [r["end_to_end_success"] for r in rows if r["end_to_end_success"] is not None]

    input_chars = sum(len(str(c["question"])) for c in cases)
    output_chars = sum(r["answer_chars"] for r in rows)
    input_tokens_est = math.ceil(input_chars / 4)
    output_tokens_est = math.ceil(output_chars / 4)
    estimated_cost = None
    if args.input_usd_per_1m_tokens is not None and args.output_usd_per_1m_tokens is not None:
        estimated_cost = round(
            input_tokens_est * args.input_usd_per_1m_tokens / 1_000_000
            + output_tokens_est * args.output_usd_per_1m_tokens / 1_000_000,
            8,
        )

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "dataset": str(args.dataset),
        "dataset_cases": len(cases),
        "workers": args.workers,
        "duration_seconds": round(elapsed, 3),
        "metrics": {
            "model_quality_pass_rate_pct": ratio(model_values),
            "model_quality_labeled_cases": len(model_values),
            "rag_citation_recall_pct": round(statistics.mean(retrieval_recalls) * 100, 2) if retrieval_recalls else None,
            "rag_citation_precision_pct": round(statistics.mean(retrieval_precisions) * 100, 2) if retrieval_precisions else None,
            "rag_retrieval_labeled_cases": len(retrieval_recalls),
            "end_to_end_task_success_pct": ratio(e2e_values),
            "end_to_end_labeled_cases": len(e2e_values),
            "latency_ms": {
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99),
                "mean": round(statistics.mean(latencies), 3) if latencies else None,
            },
            "reliability_http_success_pct": round(len(successful) / len(rows) * 100, 2) if rows else None,
            "requests_per_second": round(len(rows) / elapsed, 3) if elapsed else None,
            "cost": {
                "input_tokens_estimated": input_tokens_est,
                "output_tokens_estimated": output_tokens_est,
                "estimated_usd": estimated_cost,
                "pricing_supplied": estimated_cost is not None,
                "token_estimation": "characters divided by four; approximate only",
            },
        },
        "limitations": [
            "Citation metrics measure documents cited by the generated answer, not the hidden top-K retriever ranking.",
            "Answer-term checks are weak proxies; use reviewer-adjudicated semantic labels for publishable model-quality claims.",
            "Cost is unavailable unless provider pricing is supplied and token counts are estimated from characters; it is not provider billing data.",
            "Business impact must be measured from a real before/after workflow pilot, not inferred from API benchmarks.",
            "Use a frozen, expert-reviewed holdout set; synthetic or unreviewed labels are not independent validation.",
        ],
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report written to {args.output}")
    return 0 if len(successful) == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
