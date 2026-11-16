"""Tone check: is each line hostile, or too informal for work?

Runs two small classifiers, only when the user asks for a check, so nothing
heavy happens per keystroke: Detoxify for toxicity, and a RoBERTa formality
ranker trained on GYAFC for informality. Both are swappable through the
[tone_check] section of extension/api/config.toml.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass

from evaluation.evaluation import DetoxifyToxicityScorer


@dataclass(frozen=True)
class LineCheck:
    text: str
    toxicity: float
    informality: float
    toxic: bool
    informal: bool


class ToneChecker:
    def __init__(
        self,
        *,
        toxicity_model: str = "original",
        formality_model: str = "s-nlp/roberta-base-formality-ranker",
        toxic_threshold: float = 0.5,
        informal_threshold: float = 0.8,
    ) -> None:
        from transformers import pipeline

        self.toxic_threshold = toxic_threshold
        self.informal_threshold = informal_threshold
        self._toxicity = DetoxifyToxicityScorer(toxicity_model, device="cpu")
        self._formality = pipeline("text-classification", model=formality_model, device=-1, top_k=None)
        self.model = f"{self._toxicity.model_name} + {formality_model}"
        # The API serves requests from a thread pool; the models aren't thread-safe.
        self._lock = threading.Lock()

    def check(self, lines: Sequence[str]) -> list[LineCheck]:
        texts = [line.strip() for line in lines]
        with self._lock:
            toxicity = self._toxicity.score(texts)
            formality = self._formality(texts)
        informality = [
            next((float(label["score"]) for label in labels if label["label"].lower() == "informal"), 0.0)
            for labels in formality
        ]
        return [
            LineCheck(
                text=text,
                toxicity=round(tox, 4),
                informality=round(inf, 4),
                toxic=tox >= self.toxic_threshold,
                informal=inf >= self.informal_threshold,
            )
            for text, tox, inf in zip(texts, toxicity, informality, strict=True)
        ]
