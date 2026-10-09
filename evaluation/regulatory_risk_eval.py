"""Release-gating evaluation for retrieval, citation grounding and risk outputs.

The benchmark must be populated with expert-reviewed, jurisdiction-specific
cases before this command can pass. Synthetic examples are not a legal or
regulatory validation set.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def evaluate(records: list[dict[str, Any]], minimum_cases: int = 5) -> dict[str, Any]:
    if len(records) < minimum_cases:
        return {
            "status": "insufficient_benchmark",
            "cases": len(records),
            "minimum_cases": minimum_cases,
            "release_gate_passed": False,
        }
    retrieval_hits = 0
    grounded_count = 0
    unsupported_grounded = 0
    citation_precision_sum = 0.0
    citation_cases = 0
    risk_pairs: list[tuple[float, float]] = []
    for item in records:
        expected = set(item.get("expected_source_ids", []))
        retrieved = set(item.get("retrieved_source_ids", []))
        if expected and expected.intersection(retrieved):
            retrieval_hits += 1
        if item.get("answer_grounded") is True:
            grounded_count += 1
            cited = set(item.get("answer_citation_ids", []))
            supported = set(item.get("supported_citation_ids", []))
            precision = len(cited & supported) / len(cited) if cited else 0.0
            citation_precision_sum += precision
            citation_cases += 1
            if not cited or not cited.issubset(supported):
                unsupported_grounded += 1
        gold = item.get("gold_risk_score")
        predicted = item.get("predicted_risk_score")
        if gold is not None and predicted is not None:
            gold_value, predicted_value = float(gold), float(predicted)
            if not (0 <= gold_value <= 100 and 0 <= predicted_value <= 100):
                raise ValueError("risk scores must be between 0 and 100")
            risk_pairs.append((gold_value, predicted_value))
    result: dict[str, Any] = {
        "status": "evaluated",
        "cases": len(records),
        "retrieval_hit_rate": retrieval_hits / len(records),
        "grounded_answer_rate": grounded_count / len(records),
        "unsupported_grounded_answer_rate": (
            unsupported_grounded / grounded_count if grounded_count else None
        ),
        "mean_citation_precision": (
            citation_precision_sum / citation_cases if citation_cases else None
        ),
        "risk_labeled_cases": len(risk_pairs),
        "release_gate_passed": False,
    }
    if len(risk_pairs) >= minimum_cases:
        errors = [predicted - gold for gold, predicted in risk_pairs]
        result["risk_mae"] = sum(abs(error) for error in errors) / len(errors)
        result["risk_rmse"] = math.sqrt(sum(error * error for error in errors) / len(errors))
        result["risk_bias"] = sum(errors) / len(errors)
        result["risk_metrics_valid"] = True
    else:
        result["risk_metrics_valid"] = False
        result["risk_metrics_note"] = f"At least {minimum_cases} expert-labeled risk cases are required."
    # A production gate must additionally enforce jurisdiction-specific
    # acceptance thresholds approved by the legal/domain owner.
    result["release_gate_passed"] = (
        result["status"] == "evaluated"
        and result["unsupported_grounded_answer_rate"] == 0.0
        and result["risk_metrics_valid"]
    )
    return result


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("evaluation/regulatory_risk_golden.json")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("benchmark must be a JSON array")
    result = evaluate(records)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["release_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
