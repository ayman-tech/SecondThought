"""Local T5 rewrite service.

Loading and generation follow the research/notebooks/inference_*.ipynb notebooks:
local files only, CPU, beam search without sampling, and inputs over the token
limit are rejected instead of truncated.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .evaluation import critical_value_metrics
from .inference_from_jsonl import validate_model_files
from .rewriter import RewriteResult

# Both models were trained on single sentences, so messages are split first.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

ALL_CAPS_WORD = re.compile(r"\b[A-Z]{2,}\b")
# Real acronyms that also happen to be in the T5 vocabulary as lowercase words.
ACRONYMS_IN_VOCAB = {"PR", "PDF"}
# Too short to judge alone ("IT" may be the department), so these only count as
# shouting right next to a shouted word ("STOP IT").
SHORT_WORDS = {"AM", "AT", "BE", "DO", "GO", "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE"}

# A sentence made of only these says nothing about the work, so there's nothing
# to preserve. "This is garbage" is different: it criticises something, so it
# goes to the model.
BARE_INSULT_WORDS = {"idiot", "idiots", "moron", "morons", "loser", "losers", "jerk", "clown", "fool", "wtf", "dammit"}
BARE_INSULT_FILLER = {"you", "you're", "youre", "are", "a", "an", "such", "what", "total", "complete", "absolute", "stupid", "dumb", "damn", "fucking", "bloody"}


@dataclass(frozen=True)
class T5Step:
    name: str
    model_dir: Path
    prefix: str


def split_sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_BREAK.split(text.strip()) if part]


def is_bare_insult(sentence: str) -> bool:
    words = re.findall(r"[a-z']+", sentence.lower())
    return (
        any(word in BARE_INSULT_WORDS for word in words)
        and all(word in BARE_INSULT_WORDS or word in BARE_INSULT_FILLER for word in words)
        and not re.search(r"\d", sentence)
    )


def calm_shouting(sentence: str, vocabulary: Collection[str]) -> str:
    """Lowercase shouted words, leaving real acronyms alone.

    The models barely touch ALL-CAPS text, and the facts guard would protect it
    as an acronym anyway. The tokenizer's vocabulary tells them apart: ordinary
    words like "garbage" are in it, while "GDPR" or "API" aren't.
    """
    words = list(ALL_CAPS_WORD.finditer(sentence))
    shouted = {
        index
        for index, word in enumerate(words)
        if len(word.group()) >= 3
        and word.group() not in ACRONYMS_IN_VOCAB
        and "▁" + word.group().lower() in vocabulary
    }
    if not shouted:
        return sentence

    def touching(first: int, second: int) -> bool:
        return not sentence[words[first].end() : words[second].start()].strip()

    # Words next to a shouted one are part of the same shout: "STOP IGNORING ME".
    # Long ones count too, since "ignoring" isn't in the vocabulary and most
    # acronyms are short.
    grew = True
    while grew:
        grew = False
        for index, word in enumerate(words):
            eligible = word.group() in SHORT_WORDS or (
                len(word.group()) >= 5 and word.group() not in ACRONYMS_IN_VOCAB
            )
            if index in shouted or not eligible:
                continue
            if (index - 1 in shouted and touching(index - 1, index)) or (
                index + 1 in shouted and touching(index, index + 1)
            ):
                shouted.add(index)
                grew = True

    pieces = []
    position = 0
    for index, word in enumerate(words):
        pieces.append(sentence[position : word.start()])
        pieces.append(word.group().lower() if index in shouted else word.group())
        position = word.end()
    pieces.append(sentence[position:])
    calmed = "".join(pieces)
    # A lowercased first word needs its capital back.
    if 0 in shouted and not re.search(r"[A-Za-z]", sentence[: words[0].start()]):
        start = words[0].start()
        calmed = calmed[:start] + calmed[start].upper() + calmed[start + 1 :]
    return calmed


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
        self._vocabulary = set(self._steps[0][1].get_vocab())
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
        # A bare insult ("IDIOT!") has nothing to keep, and the model would invent
        # something. Only drop it if the message says something else as well.
        kept = [segment for segment in segments if not is_bare_insult(segment[1])]
        segments = kept or segments
        sentences = [calm_shouting(sentence, self._vocabulary) for _, sentence in segments]
        with self._lock:
            for step, tokenizer, model in self._steps:
                sentences = self._run_step(step, tokenizer, model, sentences)

        # Put sentences back on their original lines so paragraphs survive. Lines
        # that were blank stay blank; lines emptied by a dropped insult go away.
        rebuilt: list[list[str]] = [[] for _ in lines]
        for (line_number, _), sentence in zip(segments, sentences, strict=True):
            rebuilt[line_number].append(sentence)
        rewritten = "\n".join(
            " ".join(parts) for line, parts in zip(lines, rebuilt, strict=True) if parts or not line.strip()
        ).strip()
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
