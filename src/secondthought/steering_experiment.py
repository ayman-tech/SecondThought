"""Model- and feature-agnostic activation-steering experiments.

The framework learns a target-minus-source activation direction from paired text,
selects a layer/pooling candidate on disjoint held-out pairs, and applies the
frozen direction during deterministic generation.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import time
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from evaluation.evaluation import evaluate_pair


Pooling = Literal["mean", "final_token"]


@dataclass(frozen=True)
class TextPair:
    """One paired example, where target expresses more of the feature."""

    source: str
    target: str
    group: str = "all"
    row_id: str = ""


@dataclass(frozen=True)
class CandidateMetrics:
    name: str
    layer_index: int
    pooling: Pooling
    direction_norm: float
    heldout_pairs: int
    heldout_ordering_accuracy: float
    heldout_mean_projection: float
    heldout_projection_std: float
    heldout_effect_size: float


def load_gyafc_pairs(root: str | Path) -> list[TextPair]:
    """Load aligned GYAFC train files without redistributing the corpus."""

    root = Path(root).expanduser()
    domains = {
        "entertainment_music": "Entertainment_Music",
        "family_relationships": "Family_Relationships",
    }
    pairs: list[TextPair] = []
    for group, directory in domains.items():
        train = root / directory / "train"
        source_path, target_path = train / "informal", train / "formal"
        if not source_path.is_file() or not target_path.is_file():
            raise FileNotFoundError(
                f"Expected aligned GYAFC files at {source_path} and {target_path}"
            )
        sources = source_path.read_text(encoding="utf-8").splitlines()
        targets = target_path.read_text(encoding="utf-8").splitlines()
        if len(sources) != len(targets):
            raise ValueError(f"Unaligned GYAFC files for {group}")
        for index, (source, target) in enumerate(zip(sources, targets, strict=True)):
            if _normalize(source) == _normalize(target):
                continue
            pairs.append(TextPair(source, target, group, f"{group}:{index}"))
    return pairs


def load_delimited_pairs(
    path: str | Path,
    *,
    source_column: str,
    target_column: str,
    group_column: str | None = None,
) -> list[TextPair]:
    """Load feature pairs from CSV or JSONL using configurable columns."""

    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    pairs = []
    for index, row in enumerate(rows):
        group = str(row.get(group_column, "all")) if group_column else "all"
        pairs.append(
            TextPair(
                source=str(row[source_column]),
                target=str(row[target_column]),
                group=group,
                row_id=str(row.get("id", index)),
            )
        )
    return pairs


def load_huggingface_pairs(
    dataset_id: str,
    *,
    source_column: str,
    target_column: str,
    split: str = "train",
    config_name: str | None = None,
    group_column: str | None = None,
) -> list[TextPair]:
    """Load any Hugging Face paired-text dataset (for example ParaDetox)."""

    from datasets import load_dataset

    dataset = load_dataset(dataset_id, config_name, split=split)
    pairs = []
    for index, row in enumerate(dataset):
        group = str(row.get(group_column, "all")) if group_column else "all"
        pairs.append(
            TextPair(
                source=str(row[source_column]),
                target=str(row[target_column]),
                group=group,
                row_id=str(row.get("id", index)),
            )
        )
    return pairs


def stratified_split(
    pairs: Sequence[TextPair],
    *,
    extraction_pairs: int,
    heldout_pairs: int,
    seed: int,
) -> tuple[list[TextPair], list[TextPair]]:
    """Make deterministic, disjoint splits balanced across pair groups."""

    grouped: dict[str, list[TextPair]] = {}
    for pair in pairs:
        grouped.setdefault(pair.group, []).append(pair)
    rng = random.Random(seed)
    groups = sorted(grouped)

    def allocation(total: int) -> dict[str, int]:
        base, remainder = divmod(total, len(groups))
        return {group: base + (position < remainder) for position, group in enumerate(groups)}

    extraction_allocation = allocation(extraction_pairs)
    heldout_allocation = allocation(heldout_pairs)
    extraction: list[TextPair] = []
    heldout: list[TextPair] = []
    for group in groups:
        rows = list(grouped[group])
        rng.shuffle(rows)
        extraction_count = extraction_allocation[group]
        heldout_count = heldout_allocation[group]
        required = extraction_count + heldout_count
        if len(rows) < required:
            raise ValueError(
                f"Group {group!r} has {len(rows)} pairs; {required} are required"
            )
        extraction.extend(rows[:extraction_count])
        heldout.extend(rows[extraction_count:required])
    rng.shuffle(extraction)
    rng.shuffle(heldout)
    return extraction, heldout


def select_device(requested: str = "auto") -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def decoder_backbone(model):
    """Return the decoder that can emit hidden states without LM logits."""

    for name in ("model", "transformer", "gpt_neox"):
        candidate = getattr(model, name, None)
        if candidate is not None:
            return candidate
    raise TypeError(f"Unsupported causal-LM layout: {type(model).__name__}")


def decoder_layers(model):
    backbone = decoder_backbone(model)
    for name in ("layers", "h"):
        layers = getattr(backbone, name, None)
        if layers is not None:
            return layers
    raise TypeError(f"Cannot locate decoder layers on {type(backbone).__name__}")


def mean_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    expanded = mask.unsqueeze(-1).to(hidden.dtype)
    return (hidden * expanded).sum(1) / expanded.sum(1).clamp_min(1)


def final_token_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    positions = mask.sum(1) - 1
    rows = torch.arange(hidden.shape[0], device=hidden.device)
    return hidden[rows, positions]


def _representations(hidden_states, mask) -> torch.Tensor:
    # hidden_states[0] is the embedding output; layer i is hidden_states[i + 1].
    layers = hidden_states[1:]
    mean = torch.stack([mean_pool(hidden, mask) for hidden in layers], dim=1)
    final = torch.stack([final_token_pool(hidden, mask) for hidden in layers], dim=1)
    return torch.stack((mean, final), dim=0)


class SteeringExperiment:
    """Reusable paired-feature activation-steering runner."""

    def __init__(
        self,
        model_id: str,
        *,
        device: str = "auto",
        max_length: int = 128,
        batch_size: int = 16,
    ) -> None:
        self.model_id = model_id
        self.device = select_device(device)
        self.max_length = max_length
        self.batch_size = batch_size
        dtype = torch.float16 if self.device.type in {"cuda", "mps"} else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "right"
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype).to(self.device)
        self.model.eval()
        self.backbone = decoder_backbone(self.model)
        self.layers = decoder_layers(self.model)

    def _batch_representations(self, texts: list[str]) -> torch.Tensor:
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in encoded.items()}
        with torch.inference_mode():
            outputs = self.backbone(
                **inputs,
                output_hidden_states=True,
                use_cache=False,
                return_dict=True,
            )
        return _representations(outputs.hidden_states, inputs["attention_mask"])

    def extract_directions(self, pairs: Sequence[TextPair]) -> dict[str, torch.Tensor]:
        sums = None
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start:start + self.batch_size]
            count = len(batch)
            texts = [pair.source for pair in batch] + [pair.target for pair in batch]
            representations = self._batch_representations(texts)
            deltas = representations[:, count:] - representations[:, :count]
            batch_sum = deltas.float().sum(dim=1).cpu()
            sums = batch_sum if sums is None else sums + batch_sum
        if sums is None:
            raise ValueError("At least one extraction pair is required")
        means = sums / len(pairs)
        directions: dict[str, torch.Tensor] = {}
        for pooling_index, pooling in enumerate(("mean", "final_token")):
            for layer_index in range(means.shape[1]):
                directions[f"layer{layer_index}_{pooling}"] = means[pooling_index, layer_index]
        return directions

    def evaluate_candidates(
        self,
        pairs: Sequence[TextPair],
        directions: dict[str, torch.Tensor],
    ) -> list[CandidateMetrics]:
        projections: dict[str, list[torch.Tensor]] = {name: [] for name in directions}
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start:start + self.batch_size]
            count = len(batch)
            texts = [pair.source for pair in batch] + [pair.target for pair in batch]
            representations = self._batch_representations(texts)
            deltas = (representations[:, count:] - representations[:, :count]).float().cpu()
            for name, vector in directions.items():
                layer_index, pooling = parse_candidate_name(name)
                pooling_index = 0 if pooling == "mean" else 1
                unit = vector.float() / vector.float().norm().clamp_min(1e-12)
                projections[name].append(deltas[pooling_index, :, layer_index] @ unit)

        rows = []
        for name, chunks in projections.items():
            values = torch.cat(chunks)
            layer_index, pooling = parse_candidate_name(name)
            mean = values.mean().item()
            std = values.std(unbiased=True).item() if len(values) > 1 else 0.0
            rows.append(
                CandidateMetrics(
                    name=name,
                    layer_index=layer_index,
                    pooling=pooling,
                    direction_norm=directions[name].float().norm().item(),
                    heldout_pairs=len(values),
                    heldout_ordering_accuracy=(values > 0).float().mean().item(),
                    heldout_mean_projection=mean,
                    heldout_projection_std=std,
                    heldout_effect_size=mean / std if std else 0.0,
                )
            )
        return sorted(
            rows,
            key=lambda row: (row.heldout_ordering_accuracy, row.heldout_effect_size),
            reverse=True,
        )

    @contextmanager
    def steering(self, candidate: CandidateMetrics, vector: torch.Tensor, alpha: float) -> Iterator[None]:
        handle = self.layers[candidate.layer_index].register_forward_hook(
            make_steering_hook(vector, alpha)
        )
        try:
            yield
        finally:
            handle.remove()

    def prompt(self, text: str, instruction: str, demonstrations: Sequence[TextPair]) -> str:
        examples = "\n\n".join(
            f"Input: {pair.source}\nRewrite: {pair.target}" for pair in demonstrations
        )
        content = f"{instruction}\n\n{examples}\n\nInput: {text}\nRewrite:" if examples else f"{instruction}\n\nInput: {text}\nRewrite:"
        if getattr(self.tokenizer, "chat_template", None):
            return self.tokenizer.apply_chat_template(
                [{"role": "user", "content": content}],
                tokenize=False,
                add_generation_prompt=True,
            )
        return content

    def generate(
        self,
        text: str,
        *,
        candidate: CandidateMetrics,
        vector: torch.Tensor,
        alpha: float,
        instruction: str,
        demonstrations: Sequence[TextPair] = (),
        max_new_tokens: int = 64,
    ) -> str:
        prompt = self.prompt(text, instruction, demonstrations)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with self.steering(candidate, vector, alpha), torch.inference_mode():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        new_ids = generated[0, inputs["input_ids"].shape[1]:]
        decoded = self.tokenizer.decode(new_ids, skip_special_tokens=True)
        return clean_generation(decoded)


def make_steering_hook(vector: torch.Tensor, alpha: float):
    """Shift every residual-stream token by alpha times a raw mean delta."""

    def hook(module, inputs, output):
        del module, inputs
        is_tuple = isinstance(output, tuple)
        residual = output[0] if is_tuple else output
        shift = (float(alpha) * vector).to(residual.device, residual.dtype)
        modified = residual + shift.view(1, 1, -1)
        return (modified, *output[1:]) if is_tuple else modified

    return hook


def parse_candidate_name(name: str) -> tuple[int, Pooling]:
    match = re.fullmatch(r"layer(\d+)_(mean|final_token)", name)
    if not match:
        raise ValueError(f"Invalid candidate name: {name}")
    return int(match.group(1)), match.group(2)  # type: ignore[return-value]


def save_artifact(
    path: str | Path,
    *,
    model_id: str,
    dataset: dict[str, Any],
    feature: str,
    seed: int,
    extraction_pairs: int,
    heldout_pairs: int,
    directions: dict[str, torch.Tensor],
    metrics: Sequence[CandidateMetrics],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "framework_version": 1,
            "model_id": model_id,
            "dataset": dataset,
            "feature": feature,
            "direction_semantics": "target_minus_source",
            "seed": seed,
            "extraction_pairs": extraction_pairs,
            "heldout_pairs": heldout_pairs,
            "candidates": {row.name: asdict(row) for row in metrics},
            "selected_candidate": metrics[0].name,
            "raw_directions": directions,
        },
        path,
    )


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        raise ValueError("Cannot write an empty CSV")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_generation_records(path: str | Path, text_column: str) -> list[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if rows and text_column not in rows[0]:
        raise ValueError(f"Missing generation text column {text_column!r}")
    return rows


def surface_diagnostics(source: str, generated: str) -> dict[str, Any]:
    source_words = re.findall(r"\b[\w']+\b", source.lower())
    generated_words = re.findall(r"\b[\w']+\b", generated.lower())
    source_set, generated_set = set(source_words), set(generated_words)
    union = source_set | generated_set
    contractions = re.findall(r"\b\w+(?:n't|'re|'ve|'ll|'d|'m|'s)\b", generated.lower())
    slang = re.findall(r"\b(?:u|ur|r|lol|omg|idk|imo|btw|thx|wanna|gonna|gotta|cuz|kinda)\b", generated.lower())
    return {
        "output_word_count": len(generated_words),
        "word_length_ratio": (len(generated_words) + 1) / (len(source_words) + 1),
        "word_set_jaccard": len(source_set & generated_set) / len(union) if union else 1.0,
        "contraction_count": len(contractions),
        "slang_count": len(slang),
        "exclamation_count": generated.count("!"),
        "exact_copy": _normalize(source) == _normalize(generated),
        "empty_output": not generated.strip(),
        **evaluate_pair(source, generated),
    }


def summarize_outputs(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for alpha in sorted({float(row["alpha"]) for row in rows}):
        group = [row for row in rows if float(row["alpha"]) == alpha]
        numeric = (
            "word_length_ratio",
            "word_set_jaccard",
            "contraction_count",
            "slang_count",
            "exclamation_count",
            "word_overlap",
            "edit_ratio",
            "number_recall",
            "critical_value_recall",
        )
        summary = {"alpha": alpha, "examples": len(group)}
        summary.update({f"mean_{key}": sum(float(row[key]) for row in group) / len(group) for key in numeric})
        summary["exact_copy_rate"] = sum(bool(row["exact_copy"]) for row in group) / len(group)
        summary["empty_output_rate"] = sum(bool(row["empty_output"]) for row in group) / len(group)
        summary["critical_value_exact_rate"] = sum(bool(row["critical_value_exact"]) for row in group) / len(group)
        summary["missing_critical_values"] = sum(int(row["critical_value_missing_count"]) for row in group)
        summary["unsupported_critical_values"] = sum(int(row["critical_value_unsupported_count"]) for row in group)
        summaries.append(summary)
    return summaries


def clean_generation(text: str) -> str:
    """Keep the first rewrite when a base LM continues the few-shot pattern."""

    result = text.strip()
    for marker in ("\n\nInput:", "\nInput:", "\n\nRewrite:"):
        result = result.split(marker, 1)[0].strip()
    return result


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

