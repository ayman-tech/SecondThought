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
    assert result["latency_ms"] == "120.5"
