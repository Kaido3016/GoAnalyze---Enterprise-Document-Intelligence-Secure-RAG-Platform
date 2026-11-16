"""Concurrent RAG API load test. Run only against an environment you own."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(p * len(ordered) / 100) - 1)], 3)


def send(base_url: str, token: str, question: str, timeout: float) -> dict:
    url = f"{base_url.rstrip('/')}/v1/rag/answer?{urllib.parse.urlencode({'question': question})}"
    req = urllib.request.Request(
        url, data=b"", method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "X-Purpose": "case-review"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {"ok": 200 <= response.status < 300, "status": response.status,
                    "latency_ms": (time.perf_counter() - start) * 1000,
                    "grounded": bool(payload.get("grounded", False)), "error": None}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "latency_ms": (time.perf_counter() - start) * 1000,
                "grounded": False, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError, AttributeError) as exc:  # report request failures
        return {"ok": False, "status": None, "latency_ms": (time.perf_counter() - start) * 1000,
                "grounded": False, "error": type(exc).__name__}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=os.getenv("GOANALYZE_BASE_URL", "http://localhost:8080"))
    p.add_argument("--token", default=os.getenv("GOANALYZE_BEARER_TOKEN"))
    p.add_argument("--question", required=True, help="A representative, non-sensitive RAG question")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--output", type=Path, default=Path("metrics/reports/load-test.json"))
    args = p.parse_args()
    if not args.token:
        p.error("set GOANALYZE_BEARER_TOKEN or pass --token")
    if args.requests < 1 or args.concurrency < 1:
        p.error("--requests and --concurrency must be >= 1")

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        rows = list(pool.map(lambda _: send(args.base_url, args.token, args.question, args.timeout),
                             range(args.requests)))
    elapsed = time.perf_counter() - start
    latencies = [r["latency_ms"] for r in rows]
    ok = [r for r in rows if r["ok"]]
    errors = Counter(r["error"] or f"HTTP {r['status']}" for r in rows if not r["ok"])
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "requests": args.requests,
        "configured_concurrency": args.concurrency,
        "duration_seconds": round(elapsed, 3),
        "metrics": {
            "throughput_requests_per_second": round(len(rows) / elapsed, 3) if elapsed else None,
            "success_rate_pct": round(len(ok) / len(rows) * 100, 2),
            "failure_count": len(rows) - len(ok),
            "latency_ms": {
                "p50": percentile(latencies, 50), "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99), "max": round(max(latencies), 3) if latencies else None,
            },
            "grounded_response_rate_pct": round(sum(r["grounded"] for r in ok) / len(ok) * 100, 2) if ok else None,
            "errors": dict(errors),
        },
        "limitations": [
            "This is a controlled API load test, not a production capacity certification.",
            "Use a dedicated staging environment and a representative, approved test tenant.",
            "Provider rate limits, database size, cache state, and hardware must be recorded with each run.",
            "Do not send sensitive or real customer documents/questions to an unapproved test environment.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report written to {args.output}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
