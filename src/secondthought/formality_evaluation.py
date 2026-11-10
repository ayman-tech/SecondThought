"""Formality metrics for saved professional-rewrite predictions.

Two kinds of signal, kept apart in the same way as evaluation.py:

- Model scores (optional, lazy-loaded): a RoBERTa formality ranker gives each
  sentence the probability that it is formal. Messages are split the way the
  product splits them before both-t5 (per line, then per sentence, with
  ``t5_rewriter.split_sentences``), and a message score is the mean of its
  sentence scores.
- Register markers (always, rule-based): informal tokens left in the rewrite.

No thresholds and no pass/fail: raw values only, to be calibrated later against
human ratings.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from evaluation.evaluation import _average, extract_critical_values
from .t5_rewriter import split_sentences

FORMALITY_MODEL_COLUMNS = (
    "formality_original",
    "formality_rewritten",
    "formality_gain",
    "formality_min_sentence",
    "formality_min_sentence_text",
    "formality_sentence_scores",
)
REGISTER_COLUMNS = ("register_marker_count", "register_markers")
FORMALITY_COLUMNS = (*FORMALITY_MODEL_COLUMNS, *REGISTER_COLUMNS)

# Copied from TEXTING in extension/triggers.js (JavaScript, so it can't be imported).
# As there, a word only counts in lowercase, so "R" (the language) or "U" don't.
TEXTING_WORDS = frozenset({
    "u", "ur", "r", "pls", "plz", "gonna", "wanna", "gotta", "tbh", "idk", "lol",
    "omg", "b4", "thx", "cuz", "coz", "ya", "yall",
})
# ACRONYMS from extension/triggers.js plus common workplace acronyms. Needed because
# evaluation.ACRONYM_PATTERN tags every all-caps word, which would hide shouting.
# ponytail: fixed allow-list; an acronym missing here counts as a marker. Grow it from false positives.
KNOWN_ACRONYMS = frozenset({
    "ASAP", "FYI", "TODO", "NOTE", "EOD", "JSON", "HTML", "HTTP", "HTTPS", "UTC", "CEST",
    "PST", "EST", "API", "URL", "PDF", "CSV", "SQL", "AWS", "GPU", "CPU", "RAM", "USB",
    "VPN", "CEO", "CTO", "CFO", "COO", "SKU", "SLA", "KPI", "ETA", "FAQ", "NDA", "ROI",
    "OKR", "RFP", "SOW", "USD", "EUR", "GBP", "JPY", "WIP", "EOW", "OOO", "TBD",
})
WORD_TOKEN = re.compile(r"[A-Za-z0-9']+")
CAPS_WORD = re.compile(r"\b[A-Z]{3,}\b")
EXCLAMATIONS = re.compile(r"!{2,}")
QUESTIONS = re.compile(r"\?{2,}")
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿⭐⭕]"
)
# A lowercase "i" standing alone or starting a contraction ("i'm"), but not "i.e.".
LOWERCASE_I = re.compile(r"(?<![\w'.])i(?=[\s,;:!?)]|'(?:m|ll|d|ve)\b|\.(?!e\.)|$)")


class FormalityScorer(Protocol):
    def score(self, texts: Sequence[str]) -> list[float]: ...


class RobertaFormalityScorer:
    """External learned classifier: probability that a text is formal (0-1).

    ``s-nlp/roberta-base-formality-ranker`` is licensed CC BY-NC-SA 4.0
    (non-commercial). Like Detoxify, its scores need workplace-domain calibration.
    The "formal" class index is read from ``config.id2label`` (0 = informal,
    1 = formal when checked), never assumed.
    """

    def __init__(
        self,
        model_name: str = "s-nlp/roberta-base-formality-ranker",
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Install formality evaluators with: pip install -r requirements-formality.txt"
            ) from exc
        self.model_name = model_name
        self._torch = torch
        self._device = device
        self._batch_size = batch_size
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name).to(device).eval()
        labels = {str(label).lower(): int(index) for index, label in self._model.config.id2label.items()}
        if "formal" not in labels:
            raise RuntimeError(f"{model_name} has no 'formal' label: {self._model.config.id2label}")
        self._formal_index = labels["formal"]
        self._max_length = min(self._tokenizer.model_max_length, 512)

    def score(self, texts: Sequence[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(texts), self._batch_size):
            batch = self._tokenizer(
                list(texts[start:start + self._batch_size]), return_tensors="pt",
                padding=True, truncation=True, max_length=self._max_length,
            ).to(self._device)
            with self._torch.inference_mode():
                probabilities = self._model(**batch).logits.softmax(dim=-1)[:, self._formal_index]
            scores.extend(float(value) for value in probabilities.tolist())
        return scores


def message_sentences(text: str) -> list[str]:
    """Split like the product does before both-t5: per line, then per sentence."""
    sentences = [sentence for line in text.splitlines() for sentence in split_sentences(line)]
    if not sentences:
        raise ValueError("cannot score formality of an empty text")
    return sentences


def register_markers(text: str) -> list[dict[str, str]]:
    """Rule-based informal markers, in reading order. No model."""
    tickets = [(v.start or 0, v.end or 0) for v in extract_critical_values(text) if v.kind == "ticket_id"]
    found: list[tuple[int, str, str]] = []
    for match in WORD_TOKEN.finditer(text):
        if match.group() in TEXTING_WORDS:
            found.append((match.start(), "texting", match.group()))
    for match in CAPS_WORD.finditer(text):
        in_ticket = any(start <= match.start() < end for start, end in tickets)
        if match.group() not in KNOWN_ACRONYMS and not in_ticket:
            found.append((match.start(), "all_caps", match.group()))
    for kind, pattern in (("exclamations", EXCLAMATIONS), ("questions", QUESTIONS),
                          ("emoji", EMOJI), ("lowercase_i", LOWERCASE_I)):
        found.extend((match.start(), kind, match.group()) for match in pattern.finditer(text))
    return [{"kind": kind, "text": marker} for _, kind, marker in sorted(found)]


def _register_fields(rewritten: str) -> dict[str, int | str]:
    markers = register_markers(rewritten)
    return {
        "register_marker_count": len(markers),
        "register_markers": json.dumps(markers, ensure_ascii=False, separators=(",", ":")),
    }


def _formality_fields(
    original_scores: Sequence[float], sentences: Sequence[str], scores: Sequence[float]
) -> dict[str, float | str]:
    if not all(math.isfinite(float(value)) for value in (*original_scores, *scores)):
        raise ValueError("formality scores must be finite")
    original = sum(original_scores) / len(original_scores)
    rewritten = sum(scores) / len(scores)
    lowest = min(range(len(scores)), key=scores.__getitem__)
    per_sentence = [
        {"sentence": sentence, "score": round(float(score), 6)}
        for sentence, score in zip(sentences, scores, strict=True)
    ]
    return {
        "formality_original": round(float(original), 6),
        "formality_rewritten": round(float(rewritten), 6),
        "formality_gain": round(float(rewritten - original), 6),
        "formality_min_sentence": round(float(scores[lowest]), 6),
        "formality_min_sentence_text": sentences[lowest],
        "formality_sentence_scores": json.dumps(per_sentence, ensure_ascii=False, separators=(",", ":")),
    }


def formality_pair_metrics(
    original: str, rewritten: str, *, formality_scorer: FormalityScorer | None = None
) -> dict[str, float | int | str]:
    """Evaluate one pair. Use ``evaluate_formality_records`` for efficient batching."""
    result: dict[str, float | int | str] = {}
    if formality_scorer is not None:
        before, after = message_sentences(original), message_sentences(rewritten)
        scores = formality_scorer.score([*before, *after])
        if len(scores) != len(before) + len(after):
            raise ValueError("formality scorer returned the wrong number of scores")
        result.update(_formality_fields(scores[:len(before)], after, scores[len(before):]))
    return {**result, **_register_fields(rewritten)}


def evaluate_formality_records(
    records: Sequence[Mapping[str, Any]], *, formality_scorer: FormalityScorer | None = None
) -> list[dict[str, float | int | str]]:
    """Evaluate records, scoring every sentence of every row in one batched call."""
    pairs = [(str(row["original_text"]), str(row["rewritten_text"])) for row in records]
    if formality_scorer is None:
        return [_register_fields(rewritten) for _, rewritten in pairs]
    split = [(message_sentences(original), message_sentences(rewritten)) for original, rewritten in pairs]
    flattened = [sentence for before, after in split for sentence in (*before, *after)]
    scores = formality_scorer.score(flattened)
    if len(scores) != len(flattened):
        raise ValueError("formality scorer returned the wrong number of scores")
    results, position = [], 0
    for (before, after), (_, rewritten) in zip(split, pairs, strict=True):
        middle, end = position + len(before), position + len(before) + len(after)
        results.append({
            **_formality_fields(scores[position:middle], after, scores[middle:end]),
            **_register_fields(rewritten),
        })
        position = end
    return results


def summarize_formality(results: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    summary: dict[str, float | None] = {}
    if results and all("formality_gain" in row for row in results):
        summary.update({
            "average_formality_original": _average(results, "formality_original"),
            "average_formality_rewritten": _average(results, "formality_rewritten"),
            "average_formality_gain": _average(results, "formality_gain"),
            "average_formality_min_sentence": _average(results, "formality_min_sentence"),
            "formality_gain_positive_rate": round(
                sum(float(row["formality_gain"]) > 0 for row in results) / len(results), 4),
        })
    summary["register_marker_free_rate"] = (
        round(sum(int(row["register_marker_count"]) == 0 for row in results) / len(results), 4)
        if results else None
    )
    return summary
