"""Causally evaluate FLAN-T5 formality directions across layers and strengths.

Directions are learned from GYAFC train pairs. Candidate layer/pooling choices are
screened on disjoint GYAFC pairs, then intervened on during generation. GYAFC tune
references measure movement toward formal writing; workplace messages measure
preservation and expose qualitative failures.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from secondthought.evaluation import (
    SentenceTransformerSimilarityScorer,
    evaluate_records,
)
from secondthought.steering_rewriter import BASE_REWRITE_PROMPT, make_steering_hook

from run_t5_size_experiment import (
    DEFAULT_GYAFC_ROOT,
    MAX_SOURCE_LENGTH,
    MAX_TARGET_LENGTH,
    PROJECT_ROOT,
    SEED,
    collect_decoder_deltas,
    deterministic_split,
    prepare_pairs,
    rewrite_prompt,
)


DEFAULT_MODEL_ID = "google/flan-t5-base"
DEFAULT_STRENGTHS = (0.5, 1.0, 2.0, 4.0)
POOLING_NAMES = ("mean", "final_token")


def load_gyafc_train(root: Path) -> pd.DataFrame:
    parts = []
    for domain in ("Entertainment_Music", "Family_Relationships"):
        informal = (root / domain / "train" / "informal").read_text().splitlines()
        formal = (root / domain / "train" / "formal").read_text().splitlines()
        if len(informal) != len(formal):
            raise ValueError(f"Unaligned GYAFC train files for {domain}")
        parts.append(pd.DataFrame({"informal": informal, "formal": formal}))
    frame = pd.concat(parts, ignore_index=True)
    return prepare_pairs(
        frame.assign(source=frame["informal"]),
        "source",
        "informal",
        "formal",
        "formality",
    )


def load_gyafc_tune(root: Path, limit: int) -> list[dict]:
    rows = []
    for domain in ("Entertainment_Music", "Family_Relationships"):
        directory = root / domain / "tune"
        informal = (directory / "informal").read_text().splitlines()
        references = [
            (directory / f"formal.ref{index}").read_text().splitlines()
            for index in range(4)
        ]
        if any(len(reference) != len(informal) for reference in references):
            raise ValueError(f"Unaligned GYAFC tune files for {domain}")
        rows.extend(
            {
                "id": f"{domain}_{index:04d}",
                "domain": domain,
                "original_text": source,
                "references": [reference[index] for reference in references],
            }
            for index, source in enumerate(informal)
        )
    rng = np.random.default_rng(SEED)
    selected = rng.permutation(len(rows))[:limit]
    return [rows[index] for index in selected]


def extract_candidates(
    frame: pd.DataFrame,
    model,
    tokenizer,
    device: torch.device,
    extraction_pairs: int,
    heldout_pairs: int,
    batch_size: int,
    candidate_count: int,
) -> tuple[list[dict], pd.DataFrame]:
    extraction, heldout = deterministic_split(frame, extraction_pairs, heldout_pairs)
    extraction_deltas = collect_decoder_deltas(
        frame=extraction,
        label="formality/extraction",
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=batch_size,
    ).float()
    heldout_deltas = collect_decoder_deltas(
        frame=heldout,
        label="formality/heldout",
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=batch_size,
    ).float()

    rows = []
    vectors: dict[tuple[str, int], torch.Tensor] = {}
    for pooling_index, pooling in enumerate(POOLING_NAMES):
        for hidden_state_index in range(1, extraction_deltas.shape[2]):
            extraction_values = extraction_deltas[pooling_index, :, hidden_state_index]
            heldout_values = heldout_deltas[pooling_index, :, hidden_state_index]
            raw_direction = extraction_values.mean(dim=0)
            unit_direction = raw_direction / raw_direction.norm().clamp_min(1e-12)
            heldout_projection = heldout_values @ unit_direction
            half = len(extraction_values) // 2
            split_half_cosine = torch.nn.functional.cosine_similarity(
                extraction_values[:half].mean(dim=0),
                extraction_values[half:].mean(dim=0),
                dim=0,
            ).item()
            rows.append(
                {
                    "pooling": pooling,
                    "hidden_state_index": hidden_state_index,
                    "layer_index": hidden_state_index - 1,
                    "relative_depth": hidden_state_index / model.config.num_decoder_layers,
                    "raw_direction_norm": raw_direction.norm().item(),
                    "heldout_ordering_accuracy": (heldout_projection > 0).float().mean().item(),
                    "projection_effect_size": (
                        heldout_projection.mean()
                        / heldout_projection.std().clamp_min(1e-12)
                    ).item(),
                    "split_half_cosine": split_half_cosine,
                }
            )
            vectors[(pooling, hidden_state_index)] = raw_direction.cpu()

    layer_results = pd.DataFrame(rows).sort_values(
        ["heldout_ordering_accuracy", "projection_effect_size"],
        ascending=False,
    )
    selected = []
    for rank, row in enumerate(layer_results.head(candidate_count).itertuples(index=False), 1):
        selected.append(
            {
                "candidate": f"rank{rank}_{row.pooling}_layer{row.layer_index}",
                "rank": rank,
                "pooling": row.pooling,
                "hidden_state_index": int(row.hidden_state_index),
                "layer_index": int(row.layer_index),
                "relative_depth": float(row.relative_depth),
                "raw_direction_norm": float(row.raw_direction_norm),
                "heldout_ordering_accuracy": float(row.heldout_ordering_accuracy),
                "projection_effect_size": float(row.projection_effect_size),
                "split_half_cosine": float(row.split_half_cosine),
                "direction": vectors[(row.pooling, row.hidden_state_index)],
            }
        )
    return selected, layer_results


def generate(
    messages: list[str],
    candidate: dict | None,
    strength: float,
    model,
    tokenizer,
    device: torch.device,
) -> list[str]:
    encoded = tokenizer(
        [rewrite_prompt(message) for message in messages],
        padding=True,
        truncation=True,
        max_length=MAX_SOURCE_LENGTH,
        return_tensors="pt",
    ).to(device)
    handle = None
    if candidate is not None and strength != 0:
        handle = model.decoder.block[candidate["layer_index"]].register_forward_hook(
            make_steering_hook(candidate["direction"], strength)
        )
    try:
        with torch.inference_mode():
            output_ids = model.generate(
                **encoded,
                max_new_tokens=80,
                num_beams=4,
                do_sample=False,
            )
    finally:
        if handle is not None:
            handle.remove()
    return tokenizer.batch_decode(output_ids, skip_special_tokens=True)


def batched_generate(
    rows: list[dict],
    candidate: dict | None,
    strength: float,
    model,
    tokenizer,
    device: torch.device,
    batch_size: int,
) -> tuple[list[str], float]:
    outputs = []
    started = time.perf_counter()
    for start in range(0, len(rows), batch_size):
        messages = [row["original_text"] for row in rows[start : start + batch_size]]
        outputs.extend(generate(messages, candidate, strength, model, tokenizer, device))
    latency_ms = (time.perf_counter() - started) * 1000 / len(rows)
    return [output.strip() for output in outputs], latency_ms


def ngrams(tokens: list[str], order: int) -> Counter:
    return Counter(tuple(tokens[index : index + order]) for index in range(len(tokens) - order + 1))


def corpus_bleu(hypotheses: list[str], references: list[list[str]]) -> float:
    """Compute case-sensitive 4-gram corpus BLEU with add-one smoothing."""
    clipped = [0] * 4
    totals = [0] * 4
    hypothesis_length = 0
    reference_length = 0
    for hypothesis, reference_set in zip(hypotheses, references, strict=True):
        hypothesis_tokens = hypothesis.split()
        reference_tokens = [reference.split() for reference in reference_set]
        hypothesis_length += len(hypothesis_tokens)
        reference_length += min(
            (len(reference) for reference in reference_tokens),
            key=lambda length: (abs(length - len(hypothesis_tokens)), length),
        )
        for order in range(1, 5):
            hypothesis_counts = ngrams(hypothesis_tokens, order)
            maximum_reference_counts: Counter = Counter()
            for reference in reference_tokens:
                reference_counts = ngrams(reference, order)
                for gram, count in reference_counts.items():
                    maximum_reference_counts[gram] = max(maximum_reference_counts[gram], count)
            clipped[order - 1] += sum(
                min(count, maximum_reference_counts[gram])
                for gram, count in hypothesis_counts.items()
            )
            totals[order - 1] += sum(hypothesis_counts.values())
    precisions = [(match + 1) / (total + 1) for match, total in zip(clipped, totals)]
    brevity_penalty = (
        1.0
        if hypothesis_length > reference_length
        else math.exp(1 - reference_length / max(hypothesis_length, 1))
    )
    return 100 * brevity_penalty * math.exp(sum(math.log(value) for value in precisions) / 4)


def condition_rows(
    dataset: str,
    sources: list[dict],
    outputs: list[str],
    candidate: dict | None,
    strength: float,
    latency_ms: float,
) -> list[dict]:
    name = "unsteered" if candidate is None else candidate["candidate"]
    return [
        {
            "dataset": dataset,
            "id": source["id"],
            "candidate": name,
            "layer_index": None if candidate is None else candidate["layer_index"],
            "pooling": None if candidate is None else candidate["pooling"],
            "strength": strength,
            "original_text": source["original_text"],
            "generated": output,
            "references": json.dumps(source.get("references", []), ensure_ascii=False),
            "latency_ms": round(latency_ms, 2),
        }
        for source, output in zip(sources, outputs, strict=True)
    ]


def run(args: argparse.Namespace) -> None:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    device = torch.device(
        args.device
        if args.device
        else "mps" if torch.backends.mps.is_available()
        else "cuda" if torch.cuda.is_available()
        else "cpu"
    )
    run_tag = args.run_tag or args.model_id.replace("/", "_").replace("-", "_") + "_formality"
    output_dir = PROJECT_ROOT / "testing" / "results"
    artifact_dir = PROJECT_ROOT / "steering_experimentation" / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    extraction_pairs = 100 if args.smoke else args.extraction_pairs
    heldout_pairs = 50 if args.smoke else args.heldout_pairs
    gyafc_limit = 12 if args.smoke else args.gyafc_examples
    workplace_limit = 5 if args.smoke else None
    strengths = [value for value in args.strengths if value != 0]

    print(f"Loading {args.model_id} on {device}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        args.model_id, local_files_only=True
    ).to(device)
    model.eval()

    train = load_gyafc_train(args.gyafc_root)
    candidates, layer_results = extract_candidates(
        train,
        model,
        tokenizer,
        device,
        extraction_pairs,
        heldout_pairs,
        args.batch_size,
        args.candidates,
    )
    layer_results.to_csv(output_dir / f"{run_tag}_layers.csv", index=False)
    torch.save(
        {
            "format_version": 1,
            "model_id": args.model_id,
            "feature": "formality",
            "seed": SEED,
            "extraction_pairs": extraction_pairs,
            "heldout_pairs": heldout_pairs,
            "candidates": candidates,
        },
        artifact_dir / f"{run_tag}_directions.pt",
    )
    printable = [{key: value for key, value in row.items() if key != "direction"} for row in candidates]
    print("Candidate directions:\n" + json.dumps(printable, indent=2), flush=True)

    gyafc_rows = load_gyafc_tune(args.gyafc_root, gyafc_limit)
    workplace_path = PROJECT_ROOT / "data" / "workplace_eval" / "input.jsonl"
    workplace_rows = [json.loads(line) for line in workplace_path.read_text().splitlines() if line]
    if workplace_limit:
        workplace_rows = workplace_rows[:workplace_limit]

    predictions = []
    conditions = [(None, 0.0)] + [
        (candidate, strength) for candidate in candidates for strength in strengths
    ]
    for candidate, strength in conditions:
        label = "unsteered" if candidate is None else candidate["candidate"]
        for dataset, rows in (("gyafc_tune", gyafc_rows), ("workplace", workplace_rows)):
            outputs, latency_ms = batched_generate(
                rows,
                candidate,
                strength,
                model,
                tokenizer,
                device,
                args.generation_batch_size,
            )
            predictions.extend(condition_rows(dataset, rows, outputs, candidate, strength, latency_ms))
        print(f"{label}, strength={strength:g} complete", flush=True)

    predictions_frame = pd.DataFrame(predictions)
    predictions_path = output_dir / f"{run_tag}_predictions.csv"

    baseline = predictions_frame.query("candidate == 'unsteered'").set_index(["dataset", "id"])["generated"]
    predictions_frame["changed_from_unsteered"] = [
        row.generated != baseline.loc[(row.dataset, row.id)]
        for row in predictions_frame.itertuples(index=False)
    ]
    predictions_frame.to_csv(predictions_path, index=False)

    workplace = predictions_frame.query("dataset == 'workplace'").copy()
    scorer = None if args.skip_similarity else SentenceTransformerSimilarityScorer(
        "sentence-transformers/all-mpnet-base-v2", device="cpu"
    )
    metrics = evaluate_records(
        [
            {"original_text": row.original_text, "rewritten_text": row.generated}
            for row in workplace.itertuples(index=False)
        ],
        toxicity_scorer=None,
        similarity_scorer=scorer,
    )
    workplace = pd.concat([workplace.reset_index(drop=True), pd.DataFrame(metrics)], axis=1)
    workplace.to_csv(output_dir / f"{run_tag}_workplace_evaluated.csv", index=False)

    summary_rows = []
    for (candidate, strength), group in predictions_frame.groupby(["candidate", "strength"], sort=False):
        gyafc_group = group.query("dataset == 'gyafc_tune'")
        workplace_group = workplace.query("candidate == @candidate and strength == @strength")
        references = [json.loads(value) for value in gyafc_group["references"]]
        row = {
            "candidate": candidate,
            "layer_index": group["layer_index"].iloc[0],
            "pooling": group["pooling"].iloc[0],
            "strength": strength,
            "gyafc_bleu": corpus_bleu(gyafc_group["generated"].tolist(), references),
            "gyafc_copy_bleu": corpus_bleu(gyafc_group["original_text"].tolist(), references),
            "gyafc_changed": int(gyafc_group["changed_from_unsteered"].sum()),
            "workplace_changed": int(workplace_group["changed_from_unsteered"].sum()),
            "critical_values_preserved": int(workplace_group["critical_value_preserved_count"].sum()),
            "critical_values": int(workplace_group["critical_value_count"].sum()),
            "unsupported_values": int(workplace_group["critical_value_unsupported_count"].sum()),
        }
        if not args.skip_similarity:
            row["mean_semantic_similarity"] = workplace_group["semantic_similarity"].mean()
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows).sort_values("gyafc_bleu", ascending=False)
    summary.to_csv(output_dir / f"{run_tag}_summary.csv", index=False)

    metadata = {
        "model_id": args.model_id,
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "decoder_layers": model.config.num_decoder_layers,
        "hidden_size": model.config.d_model,
        "device": str(device),
        "seed": SEED,
        "prompt": BASE_REWRITE_PROMPT,
        "extraction_pairs": extraction_pairs,
        "heldout_pairs": heldout_pairs,
        "gyafc_tune_examples": len(gyafc_rows),
        "workplace_examples": len(workplace_rows),
        "strengths": strengths,
        "candidate_directions": printable,
    }
    (output_dir / f"{run_tag}_metadata.json").write_text(json.dumps(metadata, indent=2))
    print("\nSummary\n" + summary.round(4).to_string(index=False), flush=True)
    print(f"\nPredictions: {predictions_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--run-tag")
    parser.add_argument("--gyafc-root", type=Path, default=DEFAULT_GYAFC_ROOT)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--generation-batch-size", type=int, default=8)
    parser.add_argument("--extraction-pairs", type=int, default=2_000)
    parser.add_argument("--heldout-pairs", type=int, default=500)
    parser.add_argument("--gyafc-examples", type=int, default=100)
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--strengths", type=float, nargs="+", default=DEFAULT_STRENGTHS)
    parser.add_argument("--skip-similarity", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
