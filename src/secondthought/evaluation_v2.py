"""Existing metrics plus formality, without touching evaluation.py.

Every existing column keeps its name, value and order; the formality columns go
right after the existing metric columns, and metadata stays last.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .evaluation import (
    EVALUATION_COLUMNS,
    SimilarityScorer,
    ToxicityScorer,
    evaluate_records,
    format_evaluated_row,
    summarize,
)
from .formality_evaluation import (
    FORMALITY_COLUMNS,
    FormalityScorer,
    evaluate_formality_records,
    summarize_formality,
)

EVALUATION_COLUMNS_V2 = (*EVALUATION_COLUMNS, *FORMALITY_COLUMNS)
_LEADING_COLUMNS = ("id", "original_text", "rewritten_text", "response")


def evaluate_records_v2(
    records: Sequence[Mapping[str, Any]],
    *,
    toxicity_scorer: ToxicityScorer | None = None,
    similarity_scorer: SimilarityScorer | None = None,
    formality_scorer: FormalityScorer | None = None,
) -> list[dict[str, Any]]:
    existing = evaluate_records(records, toxicity_scorer=toxicity_scorer, similarity_scorer=similarity_scorer)
    formality = evaluate_formality_records(records, formality_scorer=formality_scorer)
    return [{**old, **new} for old, new in zip(existing, formality, strict=True)]


def format_evaluated_row_v2(prediction: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    """``format_evaluated_row`` order, with the formality columns after the existing metrics."""
    row = format_evaluated_row(prediction, metrics)
    head = {k: v for k, v in row.items() if k in _LEADING_COLUMNS or k in EVALUATION_COLUMNS}
    formality = {name: metrics[name] for name in FORMALITY_COLUMNS if name in metrics}
    tail = {k: v for k, v in row.items() if k not in head and k not in FORMALITY_COLUMNS}
    return {**head, **formality, **tail}


def summarize_v2(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {**summarize(results), **summarize_formality(results)}
