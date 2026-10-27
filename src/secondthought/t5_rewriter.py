"""Local T5 rewrite service.

Loading and generation follow the notebooks/inference_*.ipynb notebooks:
local files only, CPU, beam search without sampling, and inputs over the token
limit are rejected instead of truncated.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .evaluation import critical_value_metrics
from .inference_from_jsonl import validate_model_files
from .rewriter import RewriteResult

# Both models were trained on single sentences, so messages are split first.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class T5Step:
    name: str
    model_dir: Path
    prefix: str


def split_sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_BREAK.split(text.strip()) if part]


class T5Rewriter:
    """Runs each sentence through one or more T5 models in order."""

    def __init__(
        self,
        steps: Sequence[T5Step],
        *,
        max_input_tokens: int = 128,
        max_new_tokens: int = 128,
        num_beams: int = 4,
        facts_guard: bool = True,
    ) -> None:
        if not steps:
            raise ValueError("T5Rewriter needs at least one model step")
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self.max_input_tokens = max_input_tokens
        self.max_new_tokens = max_new_tokens
        self.num_beams = num_beams
        self.facts_guard = facts_guard
        folders = dict.fromkeys(Path(step.model_dir).name for step in steps)
        self.model = " + ".join(folders) + ": " + " -> ".join(step.name for step in steps)
        self._steps = []
        # A multi-task model (e.g. both-t5) serves several steps under different
        # prefixes, so each folder is loaded only once.
        loaded: dict[Path, tuple] = {}
        for step in steps:
            model_dir = Path(step.model_dir).resolve()
            if model_dir not in loaded:
                validate_model_files(model_dir)
                tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
                model = AutoModelForSeq2SeqLM.from_pretrained(model_dir, local_files_only=True)
                model.to("cpu")
                model.eval()
                loaded[model_dir] = (tokenizer, model)
            self._steps.append((step, *loaded[model_dir]))
        # Fast tokenizers can't be shared across threads, and the API serves
        # requests from a thread pool.
        self._lock = threading.Lock()

    def rewrite(self, message: str) -> RewriteResult:
        message = message.strip()
        if not message:
            raise ValueError("Message cannot be empty")

        started_at = perf_counter()
        lines = message.splitlines()
        segments = [
            (line_number, sentence)
            for line_number, line in enumerate(lines)
            for sentence in split_sentences(line)
        ]
        sentences = [sentence for _, sentence in segments]
        with self._lock:
            for step, tokenizer, model in self._steps:
                sentences = self._run_step(step, tokenizer, model, sentences)

        # Put sentences back on their original lines so paragraphs survive.
        rebuilt: list[list[str]] = [[] for _ in lines]
        for (line_number, _), sentence in zip(segments, sentences, strict=True):
            rebuilt[line_number].append(sentence)
        rewritten = "\n".join(" ".join(parts) for parts in rebuilt).strip()
        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        if not rewritten:
            raise RuntimeError("The model returned an empty rewrite")

        return RewriteResult(
            original_text=message,
            rewritten_text=rewritten,
            latency_ms=latency_ms,
            model_info=self.model,
            timestamp_utc=datetime.now(UTC).isoformat(),
        )

    def _run_step(self, step, tokenizer, model, sentences: list[str]) -> list[str]:
        texts = [step.prefix + sentence for sentence in sentences]
        longest = max(len(ids) for ids in tokenizer(texts, truncation=False)["input_ids"])
        if longest > self.max_input_tokens:
            raise ValueError(
                f"One sentence is too long for the T5 model ({longest} tokens, "
                f"limit {self.max_input_tokens}). Try breaking it into shorter sentences."
            )
        inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=False)
        with self._torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                num_beams=self.num_beams,
                do_sample=False,
            )
        outputs = [text.strip() for text in tokenizer.batch_decode(generated, skip_special_tokens=True)]
        if not all(outputs):
            raise RuntimeError(f"The {step.name} model returned an empty rewrite")
        if self.facts_guard:
            # Numbers, dates, amounts and the like must survive every step. If a
            # step drops or changes one (e.g. "2.5%" -> "2,5%"), keep that
            # sentence as it was before the step.
            outputs = [
                after if critical_value_metrics(before, after)["critical_value_exact"] else before
                for before, after in zip(sentences, outputs, strict=True)
            ]
        return outputs
