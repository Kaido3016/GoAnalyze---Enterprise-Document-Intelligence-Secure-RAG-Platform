from evaluation.regulatory_risk_eval import evaluate


def test_evaluation_fails_closed_with_insufficient_labeled_cases():
    result = evaluate([])
    assert result["status"] == "insufficient_benchmark"
    assert result["release_gate_passed"] is False


def test_evaluation_reports_retrieval_citation_and_risk_metrics():
    records = [
        {
            "expected_source_ids": ["source-a"],
            "retrieved_source_ids": ["source-a"],
            "answer_grounded": True,
            "answer_citation_ids": ["source-a"],
            "supported_citation_ids": ["source-a"],
            "gold_risk_score": float(i * 10),
            "predicted_risk_score": float(i * 10),
        }
        for i in range(5)
    ]
    result = evaluate(records)
    assert result["retrieval_hit_rate"] == 1.0
    assert result["mean_citation_precision"] == 1.0
    assert result["risk_mae"] == 0.0
    assert result["release_gate_passed"] is True
