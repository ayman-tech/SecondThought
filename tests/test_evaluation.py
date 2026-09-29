import json

import pytest

from secondthought.evaluation import (
    coerce_critical_values,
    critical_value_metrics,
    evaluate_pair,
    evaluate_records,
    extract_critical_values,
    format_evaluated_row,
    summarize,
)


class FakeToxicityScorer:
    def score(self, texts):
        assert len(texts) == 4
        return [0.9, 0.1, 0.2, 0.3]


class FakeSimilarityScorer:
    def score_pairs(self, pairs):
        assert len(pairs) == 2
        return [0.88, 0.97]


def test_evaluate_pair_detects_number_loss():
    result = evaluate_pair(
        "Send all 12 files by 5 PM.",
        "Please send the files by 5 PM.",
    )

    assert result["number_recall"] == 0.5
    assert result["exact_match"] is False


def test_summarize_reports_control_behavior():
    results = [
        {
            "number_recall": 1.0,
            "word_overlap": 1.0,
            "edit_ratio": 0.0,
            "length_ratio": 1.0,
            "exact_match": True,
        },
        {
            "number_recall": 0.5,
            "word_overlap": 0.4,
            "edit_ratio": 0.4,
            "length_ratio": 0.8,
            "exact_match": False,
        },
    ]

    summary = summarize(results)

    assert summary["average_number_recall"] == 0.75
    assert summary["average_word_overlap"] == 0.7
    assert summary["average_edit_ratio"] == 0.2
    assert summary["average_length_ratio"] == 0.9
    assert summary["exact_match_rate"] == 0.5


def test_critical_values_normalize_formatting_and_number_words():
    result = critical_value_metrics(
        "Send 2 files by 5 PM. The budget is $1,000 with a 12% limit.",
        "Please send two files by 5 p.m. The budget is $1000 with a 12 percent limit.",
    )

    assert result["critical_value_count"] == 4
    assert result["critical_value_recall"] == 1.0
    assert result["critical_value_exact"] is True


def test_critical_values_detect_changed_and_invented_values():
    result = critical_value_metrics(
        "Fix PROJ-12 by March 2 and keep latency below 100 ms.",
        "Fix PROJ-13 by March 3 and keep latency below 200 ms.",
    )

    assert result["critical_value_missing_count"] == 3
    assert result["critical_value_unsupported_count"] == 3
    missing = json.loads(result["critical_value_missing"])
    assert {value["raw"] for value in missing} == {"PROJ-12", "March 2", "100 ms"}


def test_critical_values_count_duplicate_occurrences():
    result = critical_value_metrics("Retry 3 times, then wait 3 days.", "Retry 3 times.")

    assert result["critical_value_count"] == 2
    assert result["critical_value_preserved_count"] == 1
    assert result["critical_value_recall"] == 0.5


def test_named_values_can_be_supplied_as_human_annotations():
    annotations = json.dumps(
        [
            {"type": "project", "value": "Project Atlas"},
            {"type": "requested_action", "value": "send the report"},
        ]
    )
    result = critical_value_metrics(
        "Send the Project Atlas report.",
        "Please review the report for Project Atlas.",
        annotations,
    )

    assert result["critical_value_recall"] == 0.5
    assert result["critical_value_missing_count"] == 1


def test_extracts_structured_identifiers_without_an_external_model():
    values = extract_critical_values(
        "Email dev@example.com, mention @owner, and update API_V2 for INC-42."
    )

    assert {(value.kind, value.normalized) for value in values} == {
        ("email", "dev@example.com"),
        ("mention", "@owner"),
        ("acronym", "API_V2"),
        ("ticket_id", "INC-42"),
    }


def test_learned_evaluators_are_batched_and_summarized():
    results = evaluate_records(
        [
            {"original_text": "You are useless.", "rewritten_text": "This needs revision."},
            {"original_text": "Send it today.", "rewritten_text": "Please send it today."},
        ],
        toxicity_scorer=FakeToxicityScorer(),
        similarity_scorer=FakeSimilarityScorer(),
    )
    summary = summarize(results)

    assert results[0]["toxicity_reduction"] == 0.8
    assert results[1]["toxicity_reduction"] == -0.1
    assert results[0]["semantic_similarity"] == 0.88
    assert summary["average_toxicity_reduction"] == 0.35
    assert summary["average_semantic_similarity"] == 0.925


def test_invalid_critical_value_json_is_rejected():
    with pytest.raises(ValueError, match="valid JSON"):
        coerce_critical_values("not-json")


def test_evaluated_csv_order_places_metrics_before_metadata():
    prediction = {
        "id": "one",
        "original_text": "Send 2 files.",
        "rewritten_text": "Please send 2 files.",
        "latency_ms": 25.0,
        "input_tokens": 4,
        "output_tokens": 5,
        "response_id": "must-be-removed",
        "model_info": "local-t5:test",
        "timestamp_utc": "2026-09-29T00:00:00+00:00",
    }
    metrics = evaluate_pair(
        prediction["original_text"],
        prediction["rewritten_text"],
        toxicity_scorer=type(
            "PairToxicity", (), {"score": lambda self, texts: [0.8, 0.1]}
        )(),
        similarity_scorer=type(
            "PairSimilarity", (), {"score_pairs": lambda self, pairs: [0.9]}
        )(),
    )

    result = format_evaluated_row(prediction, metrics)

    assert list(result) == [
        "id",
        "original_text",
        "rewritten_text",
        "semantic_similarity",
        "toxicity_original",
        "toxicity_rewritten",
        "toxicity_reduction",
        "toxicity_relative_reduction",
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
    assert "response_id" not in result
