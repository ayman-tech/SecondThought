"""Scores for the Explore page's response inspector.

Same models as the evaluation page, so live numbers mean the same thing:
formality (RoBERTa ranker, averaged over sentences), toxicity (Detoxify),
meaning similarity (all-mpnet-base-v2) and value preservation (the rule-based
facts check). Similarity and values only apply when the task is a rewrite.
Needs the project's evaluation extra: uv sync --extra evaluation.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from evaluation.evaluation import (
    DetoxifyToxicityScorer,
    SentenceTransformerSimilarityScorer,
    critical_value_metrics,
)
from secondthought.formality_evaluation import RobertaFormalityScorer, formality_pair_metrics

REWRITE_TASKS = {"rewrite"}


class ResponseScorer:
    def __init__(self, device: str = "cpu") -> None:
        self._toxicity = DetoxifyToxicityScorer("original", device=device)
        self._formality = RobertaFormalityScorer(device=device)
        self._similarity = SentenceTransformerSimilarityScorer(device=device)
        self.models = {
            "toxicity": self._toxicity.model_name,
            "formality": self._formality.model_name,
            "similarity": self._similarity.model_name,
        }
        self._lock = threading.Lock()  # requests arrive on a thread pool; the models aren't thread-safe

    def score(self, source: str, response: str, task: str) -> dict[str, Any]:
        if not source.strip() or not response.strip():
            raise ValueError("Both the input and the response need text to score")
        rewrite = task in REWRITE_TASKS
        with self._lock:
            toxicity = self._toxicity.score([source, response])
            formality = formality_pair_metrics(source, response, formality_scorer=self._formality)
            similarity = self._similarity.score_pairs([(source, response)])[0] if rewrite else None
        values = None
        if rewrite:
            facts = critical_value_metrics(source, response)
            values = {
                "count": facts["critical_value_count"],
                "kept": facts["critical_value_preserved_count"],
                "missing": [v["raw"] for v in json.loads(facts["critical_value_missing"])],
                "added": [v["raw"] for v in json.loads(facts["critical_value_unsupported"])],
            }
        return {
            "formality": {
                "input": round(formality["formality_original"], 4),
                "response": round(formality["formality_rewritten"], 4),
                "lowest": round(formality["formality_min_sentence"], 4),
                "lowest_sentence": formality["formality_min_sentence_text"],
            },
            "toxicity": {"input": round(toxicity[0], 4), "response": round(toxicity[1], 4)},
            "similarity": None if similarity is None else round(similarity, 4),
            "values": values,
            "models": self.models,
        }
