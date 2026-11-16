"""Calculate workflow impact from paired, observed before/after task timings."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, required=True,
                   help="CSV columns: task_id,baseline_seconds,assisted_seconds")
    p.add_argument("--tasks-per-month", type=int, required=True,
                   help="Observed monthly task volume for the same workflow")
    p.add_argument("--loaded-hourly-cost", type=float, default=None,
                   help="Optional fully-loaded labor cost in CAD/hour")
    p.add_argument("--output", type=Path, default=Path("metrics/reports/business-impact.json"))
    args = p.parse_args()
    if args.tasks_per_month < 1:
        p.error("--tasks-per-month must be >= 1")

    samples = []
    with args.csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            baseline = float(row["baseline_seconds"])
            assisted = float(row["assisted_seconds"])
            if baseline <= 0 or assisted < 0:
                raise ValueError("baseline_seconds must be > 0 and assisted_seconds >= 0")
            samples.append((row.get("task_id", str(len(samples) + 1)), baseline, assisted))
    if not samples:
        raise ValueError("CSV contains no timing samples")

    baseline_mean = statistics.mean(x[1] for x in samples)
    assisted_mean = statistics.mean(x[2] for x in samples)
    saved_per_task = baseline_mean - assisted_mean
    reduction_pct = saved_per_task / baseline_mean * 100
    monthly_hours = saved_per_task * args.tasks_per_month / 3600
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_count": len(samples),
        "monthly_task_volume": args.tasks_per_month,
        "metrics": {
            "baseline_mean_seconds_per_task": round(baseline_mean, 3),
            "assisted_mean_seconds_per_task": round(assisted_mean, 3),
            "time_saved_seconds_per_task": round(saved_per_task, 3),
            "time_reduction_pct": round(reduction_pct, 2),
            "estimated_hours_saved_per_month": round(monthly_hours, 2),
            "estimated_hours_saved_per_year": round(monthly_hours * 12, 2),
            "estimated_monthly_labor_value_cad": round(monthly_hours * args.loaded_hourly_cost, 2)
                if args.loaded_hourly_cost is not None else None,
        },
        "methodology": [
            "Paired, observed task timings supplied by the operator; this script does not fabricate a baseline.",
            "Monthly and annual values extrapolate the measured mean to the supplied task volume.",
            "Report task mix, operator count, observation dates, and sample selection alongside this result.",
            "A before/after comparison is not causal proof unless confounders and workflow differences are controlled.",
        ],
        "samples": [
            {"task_id": task_id, "baseline_seconds": baseline, "assisted_seconds": assisted}
            for task_id, baseline, assisted in samples
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
