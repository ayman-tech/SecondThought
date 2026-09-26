"""Small, model-independent diagnostics for baseline experiments."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

NUMBER_PATTERN = re.compile(r"\b\d+(?:[.:]\d+)?\b")
WORD_PATTERN = re.compile(r"\b[\w']+\b")


def extract_numbers(text: str) -> list[str]:
    return NUMBER_PATTERN.findall(text)


def evaluate_pair(original: str, rewritten: str) -> dict[str, float | bool]:
    original_numbers = extract_numbers(original)
    rewritten_numbers = extract_numbers(rewritten)
    original_number_counts = Counter(original_numbers)
    rewritten_number_counts = Counter(rewritten_numbers)
    preserved_number_count = sum(
        min(count, rewritten_number_counts[number])
        for number, count in original_number_counts.items()
    )
    number_recall = (
        preserved_number_count / len(original_numbers) if original_numbers else 1.0
    )

    original_words = set(WORD_PATTERN.findall(original.lower()))
    rewritten_words = set(WORD_PATTERN.findall(rewritten.lower()))
    combined_words = original_words | rewritten_words
    word_overlap = (
        len(original_words & rewritten_words) / len(combined_words)
        if combined_words
        else 1.0
    )

    return {
        "number_recall": round(number_recall, 4),
        "word_overlap": round(word_overlap, 4),
        "edit_ratio": round(1 - SequenceMatcher(None, original, rewritten).ratio(), 4),
        "length_ratio": round(len(rewritten) / len(original), 4) if original else 1.0,
        "exact_match": original.strip() == rewritten.strip(),
    }


def summarize(results: list[dict[str, float | bool]]) -> dict[str, float | int | None]:
    count = len(results)
    return {
        "examples": count,
        "average_number_recall": _average(results, "number_recall"),
        "average_word_overlap": _average(results, "word_overlap"),
        "average_edit_ratio": _average(results, "edit_ratio"),
        "average_length_ratio": _average(results, "length_ratio"),
        "exact_match_rate": _rate(results, "exact_match"),
    }


def _rate(records: list[dict[str, float | bool]], field: str) -> float | None:
    if not records:
        return None
    return round(sum(bool(record[field]) for record in records) / len(records), 4)


def _average(records: list[dict[str, float | bool]], field: str) -> float | None:
    if not records:
        return None
    return round(sum(float(record[field]) for record in records) / len(records), 4)
