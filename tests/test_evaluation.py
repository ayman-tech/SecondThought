from secondthought.evaluation import evaluate_pair, summarize


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
