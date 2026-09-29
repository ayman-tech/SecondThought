from secondthought.cli import run_evaluation
from secondthought.data import read_csv, write_csv


def test_evaluation_keeps_model_and_timestamp_at_end(tmp_path):
    predictions = tmp_path / "predictions.csv"
    evaluated = tmp_path / "evaluated.csv"
    write_csv(
        predictions,
        [
            {
                "id": "one",
                "original_text": "Send 2 files.",
                "rewritten_text": "Please send 2 files.",
                "latency_ms": 120.5,
                "input_tokens": 10,
                "output_tokens": 5,
                "response_id": "response-1",
                "model_info": "test-model",
                "timestamp_utc": "2026-09-22T12:00:00+00:00",
            }
        ],
    )

    run_evaluation(str(predictions), str(evaluated))

    result = read_csv(evaluated)[0]
    assert list(result)[-2:] == ["model_info", "timestamp_utc"]
    assert "response_id" not in result
    assert list(result) == [
        "id",
        "original_text",
        "rewritten_text",
        "critical_value_count",
        "critical_value_preserved_count",
        "critical_value_recall",
        "critical_value_missing_count",
        "critical_value_unsupported_count",
        "critical_value_exact",
        "critical_value_missing",
        "critical_value_unsupported",
        "word_overlap",
        "edit_ratio",
        "length_ratio",
        "exact_match",
        "number_recall",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "model_info",
        "timestamp_utc",
    ]
    assert result["latency_ms"] == "120.5"
