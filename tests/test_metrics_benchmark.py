from scripts.metrics.benchmark_rag import evaluate


def test_retrieval_ranking_metrics_use_expected_chunk_ids():
    result = evaluate({
        "case": {
            "id": "retrieval-001",
            "question": "Find the retention rule",
            "expected_chunk_ids": ["chunk-a", "chunk-b"],
            "expected_grounded": True,
        },
        "body": {
            "statement": "Retention is seven years [chunk:chunk-a]",
            "explanation": "",
            "grounded": True,
            "citations": [],
            "retrieval_trace": [
                {"chunk_id": "chunk-x", "score": 0.99},
                {"chunk_id": "chunk-a", "score": 0.95},
                {"chunk_id": "chunk-b", "score": 0.90},
            ],
        },
        "latency_ms": 12.5,
        "error": None,
    })
    assert result["retrieval_recall_at_k"] == 1.0
    assert result["retrieval_mrr"] == 0.5
    assert 0 < result["retrieval_ndcg_at_k"] < 1
    assert result["retrieval_trace_available"] is True


def test_retrieval_metrics_are_unavailable_without_trace():
    result = evaluate({
        "case": {"id": "retrieval-002", "question": "Find the rule", "expected_chunk_ids": ["chunk-a"]},
        "body": {"statement": "No answer", "grounded": False, "citations": []},
        "latency_ms": 1.0,
        "error": None,
    })
    assert result["retrieval_recall_at_k"] is None
    assert result["retrieval_mrr"] is None
    assert result["retrieval_ndcg_at_k"] is None
    assert result["retrieval_trace_available"] is False
