import json

import pytest

from secondthought.formality_evaluation import (
    FORMALITY_COLUMNS,
    evaluate_formality_records,
    formality_pair_metrics,
    message_sentences,
    register_markers,
    summarize_formality,
)


class FakeScorer:
    """Fixed score per sentence (0.5 if unknown); records every call."""

    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def score(self, texts):
        self.calls.append(list(texts))
        return [self.scores.get(text, 0.5) for text in texts]


def kinds(text):
    return [(m["kind"], m["text"]) for m in register_markers(text)]


def test_texting_words_count_only_in_lowercase():
    assert kinds("u gonna send it? R is a language.") == [("texting", "u"), ("texting", "gonna")]


def test_all_caps_skips_known_acronyms_and_tickets():
    assert kinds("The API broke JIRA-123 again, STOP IT NOW") == [("all_caps", "STOP"), ("all_caps", "NOW")]
    assert kinds("Send the PDF ASAP.") == []


def test_punctuation_emoji_and_lowercase_i():
    assert kinds("Why?? Fix it!! 😡") == [("questions", "??"), ("exclamations", "!!"), ("emoji", "😡")]
    assert kinds("i think i'm right, i.e. done.") == [("lowercase_i", "i"), ("lowercase_i", "i")]
    assert kinds("Wow! Really?") == []


def test_contractions_are_not_markers():
    assert kinds("I'll check it, but I don't think we're done and it isn't ready.") == []


def test_sentence_split_matches_the_product():
    assert message_sentences("Fix it. Now!\nThanks? Bye") == ["Fix it.", "Now!", "Thanks?", "Bye"]
    with pytest.raises(ValueError):
        message_sentences("   ")


def test_mean_min_and_gain():
    scorer = FakeScorer({"yo fix it": 0.1, "Please fix it.": 0.9, "Thanks.": 0.6})
    result = formality_pair_metrics("yo fix it", "Please fix it. Thanks.", formality_scorer=scorer)
    assert result["formality_original"] == 0.1
    assert result["formality_rewritten"] == 0.75
    assert result["formality_gain"] == 0.65
    assert result["formality_min_sentence"] == 0.6
    assert result["formality_min_sentence_text"] == "Thanks."
    assert json.loads(result["formality_sentence_scores"]) == [
        {"sentence": "Please fix it.", "score": 0.9}, {"sentence": "Thanks.", "score": 0.6}]
    assert set(result) == set(FORMALITY_COLUMNS)


def test_without_scorer_only_register_fields():
    result = formality_pair_metrics("a", "u there??")
    assert set(result) == {"register_marker_count", "register_markers"}
    assert result["register_marker_count"] == 2
    assert json.loads(result["register_markers"]) == [
        {"kind": "texting", "text": "u"}, {"kind": "questions", "text": "??"}]


def test_batching_scores_once_and_maps_back_to_rows():
    scorer = FakeScorer({"A.": 0.1, "B.": 0.2, "C.": 0.3, "D.": 0.4, "E.": 0.5, "F.": 0.9})
    records = [
        {"original_text": "A. B.", "rewritten_text": "C."},
        {"original_text": "D.", "rewritten_text": "E. F."},
    ]
    results = evaluate_formality_records(records, formality_scorer=scorer)
    assert scorer.calls == [["A.", "B.", "C.", "D.", "E.", "F."]]
    assert (results[0]["formality_original"], results[0]["formality_rewritten"]) == (0.15, 0.3)
    assert (results[1]["formality_original"], results[1]["formality_rewritten"]) == (0.4, 0.7)
    assert results[1]["formality_min_sentence_text"] == "E."
    for row in results:
        json.loads(row["formality_sentence_scores"])
        json.loads(row["register_markers"])
    single = formality_pair_metrics("D.", "E. F.", formality_scorer=FakeScorer(scorer.scores))
    assert single == results[1]


def test_bad_scorer_output_raises():
    with pytest.raises(ValueError):
        formality_pair_metrics("a.", "b.", formality_scorer=FakeScorer({"a.": float("nan")}))

    class Short:
        def score(self, texts):
            return [0.5]

    with pytest.raises(ValueError):
        evaluate_formality_records([{"original_text": "a.", "rewritten_text": "b."}], formality_scorer=Short())


def test_summary_skips_model_fields_unless_every_row_has_them():
    rows = [
        {"formality_original": 0.2, "formality_rewritten": 0.8, "formality_gain": 0.6,
         "formality_min_sentence": 0.7, "register_marker_count": 0},
        {"formality_original": 0.5, "formality_rewritten": 0.4, "formality_gain": -0.1,
         "formality_min_sentence": 0.3, "register_marker_count": 2},
    ]
    summary = summarize_formality(rows)
    assert summary["average_formality_gain"] == 0.25
    assert summary["formality_gain_positive_rate"] == 0.5
    assert summary["register_marker_free_rate"] == 0.5
    partial = summarize_formality([rows[0], {"register_marker_count": 0}])
    assert partial == {"register_marker_free_rate": 1.0}
    assert summarize_formality([]) == {"register_marker_free_rate": None}


def test_real_model_ranks_formal_above_informal():
    pytest.importorskip("transformers")
    pytest.importorskip("torch")
    from secondthought.formality_evaluation import RobertaFormalityScorer

    formal, informal = RobertaFormalityScorer().score([
        "I would be grateful if you could send the report by Friday.",
        "yo u gonna send that report or what lol",
    ])
    assert formal > 0.5 > informal
