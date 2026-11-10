from secondthought.evaluation import evaluate_records, format_evaluated_row, summarize
from secondthought.evaluation_v2 import (
    EVALUATION_COLUMNS_V2,
    evaluate_records_v2,
    format_evaluated_row_v2,
    summarize_v2,
)
from secondthought.formality_evaluation import FORMALITY_COLUMNS

RECORDS = [
    {"id": "a", "original_text": "This stupid loop hits the API 20 times. Fix it by 5 PM!!",
     "rewritten_text": "This loop hits the API 20 times. Please fix it by 5 PM."},
    {"id": "b", "original_text": "u gonna send the $480 invoice?", "rewritten_text": "Will you send the $480 invoice?"},
]


class Fixed:
    def __init__(self, value):
        self.value = value

    def score(self, texts):
        return [self.value] * len(texts)

    def score_pairs(self, pairs):
        return [self.value] * len(pairs)


def test_existing_columns_and_values_unchanged():
    for scorers in ({}, {"toxicity_scorer": Fixed(0.3), "similarity_scorer": Fixed(0.9)}):
        old = evaluate_records(RECORDS, **scorers)
        new = evaluate_records_v2(RECORDS, formality_scorer=Fixed(0.7), **scorers)
        for before, after in zip(old, new, strict=True):
            assert {k: after[k] for k in before} == before
            assert set(after) - set(before) == set(FORMALITY_COLUMNS)


def test_row_order_keeps_existing_order_and_inserts_formality_after_metrics():
    prediction = {**RECORDS[0], "latency_ms": 12, "model_info": "m", "timestamp_utc": "t"}
    metrics = evaluate_records_v2([RECORDS[0]], formality_scorer=Fixed(0.7))[0]
    old = format_evaluated_row(prediction, metrics)
    new = format_evaluated_row_v2(prediction, metrics)
    assert [k for k in new if k not in FORMALITY_COLUMNS] == list(old)
    assert {k: new[k] for k in old} == old
    keys = list(new)
    assert keys.index("number_recall") < keys.index("formality_original") < keys.index("latency_ms")
    assert keys[-2:] == ["model_info", "timestamp_utc"]
    assert EVALUATION_COLUMNS_V2[-len(FORMALITY_COLUMNS):] == FORMALITY_COLUMNS


def test_summary_is_the_old_summary_plus_formality():
    results = evaluate_records_v2(RECORDS, formality_scorer=Fixed(0.7))
    summary = summarize_v2(results)
    assert {k: summary[k] for k in summarize(results)} == summarize(results)
    assert summary["average_formality_gain"] == 0.0
    assert summary["register_marker_free_rate"] == 1.0
