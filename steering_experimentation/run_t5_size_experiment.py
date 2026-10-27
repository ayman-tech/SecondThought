"""Run a controlled FLAN-T5 activation-steering size experiment.

The default run repeats the existing FLAN-T5-small protocol with
``google/flan-t5-base``. It changes the checkpoint and extraction batch size,
while keeping the paired data, split seed, prompt, direction construction,
generation settings, steering grid, workplace inputs, and evaluators fixed.
"""

from __future__ import annotations

import argparse
import json
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import load_dataset
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from secondthought.evaluation import (
    DetoxifyToxicityScorer,
    SentenceTransformerSimilarityScorer,
    evaluate_records,
)
from secondthought.steering_rewriter import BASE_REWRITE_PROMPT, make_steering_hook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GYAFC_ROOT = Path("/Users/nandanprince/Downloads/GYAFC_Corpus")
DEFAULT_MODEL_ID = "google/flan-t5-base"
PARADETOX_ID = "s-nlp/paradetox"
SEED = 42
MAX_SOURCE_LENGTH = 192
MAX_TARGET_LENGTH = 96
ALPHAS = (0.0, 1.0, 2.0)
BETAS = (0.0, 1.0, 2.0)


@dataclass(frozen=True)
class FeatureDataset:
    key: str
    negative_label: str
    positive_label: str
    pairs: pd.DataFrame


def normalize_text(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def prepare_pairs(
    frame: pd.DataFrame,
    source_column: str,
    negative_column: str,
    positive_column: str,
    feature: str,
) -> pd.DataFrame:
    result = frame[[source_column, negative_column, positive_column]].rename(
        columns={
            source_column: "source",
            negative_column: "negative",
            positive_column: "positive",
        }
    ).copy()
    for column in ("source", "negative", "positive"):
        result[column] = result[column].fillna("").astype(str).str.strip()
    result = result.loc[(result[["source", "negative", "positive"]] != "").all(axis=1)]
    result["negative_key"] = result["negative"].map(normalize_text)
    result["positive_key"] = result["positive"].map(normalize_text)
    result = result.loc[result["negative_key"] != result["positive_key"]]
    result = result.drop_duplicates(["negative_key", "positive_key"])
    result = result.sample(frac=1, random_state=SEED).drop_duplicates("negative_key")
    result["feature"] = feature
    return result.reset_index(drop=True)


def load_feature_datasets(gyafc_root: Path) -> dict[str, FeatureDataset]:
    gyafc_parts = []
    for domain in ("Entertainment_Music", "Family_Relationships"):
        informal = (gyafc_root / domain / "train" / "informal").read_text().splitlines()
        formal = (gyafc_root / domain / "train" / "formal").read_text().splitlines()
        if len(informal) != len(formal):
            raise ValueError(f"Unaligned GYAFC train files for {domain}")
        gyafc_parts.append(pd.DataFrame({"informal": informal, "formal": formal}))
    gyafc = pd.concat(gyafc_parts, ignore_index=True)
    formality = prepare_pairs(
        gyafc.assign(source=gyafc["informal"]),
        "source",
        "informal",
        "formal",
        "formality",
    )

    paradetox = load_dataset(PARADETOX_ID, split="train")
    detox_frame = paradetox.select_columns(
        ["en_toxic_comment", "en_neutral_comment"]
    ).to_pandas()
    detoxification = prepare_pairs(
        detox_frame.assign(source=detox_frame["en_toxic_comment"]),
        "source",
        "en_toxic_comment",
        "en_neutral_comment",
        "detoxification",
    )
    return {
        "formality": FeatureDataset("formality", "informal", "formal", formality),
        "detoxification": FeatureDataset(
            "detoxification", "toxic", "neutral", detoxification
        ),
    }


def deterministic_split(
    frame: pd.DataFrame, extraction_pairs: int, heldout_pairs: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = extraction_pairs + heldout_pairs
    if len(frame) < required:
        raise ValueError(f"Need {required:,} pairs; found {len(frame):,}")
    positions = np.random.default_rng(SEED).permutation(len(frame))[:required]
    extraction = frame.iloc[positions[:extraction_pairs]].reset_index(drop=True)
    heldout = frame.iloc[positions[extraction_pairs:]].reset_index(drop=True)
    return extraction, heldout


def mean_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    expanded = mask.unsqueeze(-1).to(hidden.dtype)
    return (hidden * expanded).sum(dim=1) / expanded.sum(dim=1).clamp_min(1)


def final_token_pool(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    positions = mask.sum(dim=1) - 1
    batch = torch.arange(hidden.shape[0], device=hidden.device)
    return hidden[batch, positions]


def rewrite_prompt(message: str) -> str:
    return f"{BASE_REWRITE_PROMPT}\n\nMessage:\n{message}"


def collect_decoder_deltas(
    *,
    frame: pd.DataFrame,
    label: str,
    model,
    tokenizer,
    device: torch.device,
    batch_size: int,
) -> torch.Tensor:
    pair_count = len(frame)
    depth_count = model.config.num_decoder_layers + 1
    deltas = torch.empty(
        (2, pair_count, depth_count, model.config.d_model), dtype=torch.float16
    )
    started = time.perf_counter()
    for batch_number, start in enumerate(range(0, pair_count, batch_size), 1):
        stop = min(start + batch_size, pair_count)
        batch = frame.iloc[start:stop]
        size = len(batch)
        sources = [rewrite_prompt(text) for text in batch["source"]]
        targets = batch["negative"].tolist() + batch["positive"].tolist()
        encoder = tokenizer(
            sources + sources,
            padding=True,
            truncation=True,
            max_length=MAX_SOURCE_LENGTH,
            return_tensors="pt",
        ).to(device)
        target = tokenizer(
            text_target=targets,
            padding=True,
            truncation=True,
            max_length=MAX_TARGET_LENGTH,
            return_tensors="pt",
        ).to(device)
        labels = target["input_ids"].clone()
        labels[labels == tokenizer.pad_token_id] = -100
        with torch.inference_mode():
            outputs = model(
                **encoder,
                labels=labels,
                decoder_attention_mask=target["attention_mask"],
                output_hidden_states=True,
                use_cache=False,
                return_dict=True,
            )
        for depth, hidden in enumerate(outputs.decoder_hidden_states):
            mean = mean_pool(hidden, target["attention_mask"])
            final = final_token_pool(hidden, target["attention_mask"])
            deltas[0, start:stop, depth] = (mean[size:] - mean[:size]).cpu().half()
            deltas[1, start:stop, depth] = (final[size:] - final[:size]).cpu().half()
        if batch_number == 1 or batch_number % 25 == 0 or stop == pair_count:
            elapsed = time.perf_counter() - started
            print(f"{label}: {stop:,}/{pair_count:,} pairs · {elapsed:.1f}s", flush=True)
    return deltas


def extract_features(
    *,
    datasets: dict[str, FeatureDataset],
    model,
    tokenizer,
    device: torch.device,
    extraction_pairs: int,
    heldout_pairs: int,
    batch_size: int,
) -> tuple[dict[str, dict], pd.DataFrame]:
    pooling_names = ("mean", "final_token")
    rows: list[dict] = []
    directions: dict[tuple[str, str, int], torch.Tensor] = {}
    for feature_key, spec in datasets.items():
        extraction, heldout = deterministic_split(
            spec.pairs, extraction_pairs, heldout_pairs
        )
        split_deltas = {
            "extraction": collect_decoder_deltas(
                frame=extraction,
                label=f"{feature_key}/extraction",
                model=model,
                tokenizer=tokenizer,
                device=device,
                batch_size=batch_size,
            ).float(),
            "heldout": collect_decoder_deltas(
                frame=heldout,
                label=f"{feature_key}/heldout",
                model=model,
                tokenizer=tokenizer,
                device=device,
                batch_size=batch_size,
            ).float(),
        }
        for pooling_index, pooling in enumerate(pooling_names):
            extraction_values = split_deltas["extraction"][pooling_index]
            heldout_values = split_deltas["heldout"][pooling_index]
            for hidden_state_index in range(extraction_values.shape[1]):
                extraction_at_layer = extraction_values[:, hidden_state_index]
                heldout_at_layer = heldout_values[:, hidden_state_index]
                raw_direction = extraction_at_layer.mean(dim=0)
                unit_direction = raw_direction / raw_direction.norm().clamp_min(1e-12)
                heldout_projection = heldout_at_layer @ unit_direction
                half = len(extraction_at_layer) // 2
                half_a = extraction_at_layer[:half].mean(dim=0)
                half_b = extraction_at_layer[half:].mean(dim=0)
                split_half_cosine = torch.nn.functional.cosine_similarity(
                    half_a, half_b, dim=0
                ).item()
                rows.append(
                    {
                        "feature": feature_key,
                        "pooling": pooling,
                        "hidden_state_index": hidden_state_index,
                        "layer_index": hidden_state_index - 1,
                        "relative_depth": (
                            hidden_state_index / model.config.num_decoder_layers
                        ),
                        "raw_direction_norm": raw_direction.norm().item(),
                        "heldout_ordering_accuracy": (
                            (heldout_projection > 0).float().mean().item()
                        ),
                        "projection_effect_size": (
                            heldout_projection.mean()
                            / heldout_projection.std().clamp_min(1e-12)
                        ).item(),
                        "split_half_cosine": split_half_cosine,
                    }
                )
                directions[(feature_key, pooling, hidden_state_index)] = raw_direction.cpu()

    layer_results = pd.DataFrame(rows)
    hookable = layer_results.query("hidden_state_index >= 1").copy()
    selected = (
        hookable.sort_values(
            ["feature", "heldout_ordering_accuracy", "projection_effect_size"],
            ascending=[True, False, False],
        )
        .groupby("feature", as_index=False)
        .head(1)
    )
    features: dict[str, dict] = {}
    for row in selected.itertuples(index=False):
        spec = datasets[row.feature]
        features[row.feature] = {
            "negative_label": spec.negative_label,
            "positive_label": spec.positive_label,
            "layer_index": int(row.layer_index),
            "hidden_state_index": int(row.hidden_state_index),
            "relative_depth": float(row.relative_depth),
            "pooling": row.pooling,
            "direction": directions[(row.feature, row.pooling, row.hidden_state_index)],
            "coefficient_scale": 1.0,
            "raw_direction_norm": float(row.raw_direction_norm),
            "heldout_ordering_accuracy": float(row.heldout_ordering_accuracy),
            "projection_effect_size": float(row.projection_effect_size),
            "split_half_cosine": float(row.split_half_cosine),
        }
    return features, layer_results


def generate_batch(
    *, model, tokenizer, device: torch.device, features: dict[str, dict],
    messages: list[str], alpha: float, beta: float
) -> list[str]:
    encoded = tokenizer(
        [rewrite_prompt(message) for message in messages],
        padding=True,
        truncation=True,
        max_length=MAX_SOURCE_LENGTH,
        return_tensors="pt",
    ).to(device)
    controls = {"formality": alpha, "detoxification": beta}
    with ExitStack() as stack:
        for feature_key, coefficient in controls.items():
            if coefficient == 0:
                continue
            metadata = features[feature_key]
            handle = model.decoder.block[metadata["layer_index"]].register_forward_hook(
                make_steering_hook(metadata["direction"], coefficient)
            )
            stack.callback(handle.remove)
        with torch.inference_mode():
            output_ids = model.generate(
                **encoded,
                max_new_tokens=80,
                num_beams=4,
                do_sample=False,
            )
    return [text.strip() for text in tokenizer.batch_decode(output_ids, skip_special_tokens=True)]


def run(args: argparse.Namespace) -> None:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    output_dir = PROJECT_ROOT / "testing" / "results"
    artifact_dir = PROJECT_ROOT / "steering_experimentation" / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_tag = args.run_tag or args.model_id.replace("/", "_").replace("-", "_")
    if args.smoke:
        run_tag += "_smoke"
    paths = {
        "artifact": artifact_dir / f"{run_tag}_feature_directions.pt",
        "layers": output_dir / f"{run_tag}_feature_layer_results.csv",
        "predictions": output_dir / f"{run_tag}_steering_predictions.csv",
        "evaluated": output_dir / f"{run_tag}_steering_evaluated.csv",
        "summary": output_dir / f"{run_tag}_steering_summary.csv",
        "review": output_dir / f"{run_tag}_qualitative_review.csv",
        "metadata": output_dir / f"{run_tag}_run_metadata.json",
    }

    device = torch.device(
        args.device
        if args.device
        else "mps" if torch.backends.mps.is_available()
        else "cuda" if torch.cuda.is_available()
        else "cpu"
    )
    extraction_pairs = 100 if args.smoke else args.extraction_pairs
    heldout_pairs = 50 if args.smoke else args.heldout_pairs
    print(f"Loading {args.model_id} on {device}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model_id).to(device)
    model.eval()
    model_metadata = {
        "model_id": args.model_id,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "encoder_layers": int(model.config.num_layers),
        "decoder_layers": int(model.config.num_decoder_layers),
        "hidden_size": int(model.config.d_model),
        "device": str(device),
        "seed": SEED,
        "extraction_pairs_per_feature": extraction_pairs,
        "heldout_pairs_per_feature": heldout_pairs,
        "batch_size": args.batch_size,
        "alphas": ALPHAS,
        "betas": BETAS,
        "prompt": BASE_REWRITE_PROMPT,
    }
    print(json.dumps(model_metadata, indent=2), flush=True)

    datasets = load_feature_datasets(args.gyafc_root)
    features, layer_results = extract_features(
        datasets=datasets,
        model=model,
        tokenizer=tokenizer,
        device=device,
        extraction_pairs=extraction_pairs,
        heldout_pairs=heldout_pairs,
        batch_size=args.batch_size,
    )
    layer_results.to_csv(paths["layers"], index=False)
    artifact = {
        "format_version": 1,
        "model_id": args.model_id,
        "architecture": "encoder_decoder",
        "intervention_site": "decoder_blocks",
        "base_prompt": BASE_REWRITE_PROMPT,
        "seed": SEED,
        "extraction_pairs_per_feature": extraction_pairs,
        "heldout_pairs_per_feature": heldout_pairs,
        "features": features,
    }
    torch.save(artifact, paths["artifact"])
    selected_metadata = {
        key: {name: value for name, value in feature.items() if name != "direction"}
        for key, feature in features.items()
    }
    model_metadata["selected_features"] = selected_metadata
    paths["metadata"].write_text(json.dumps(model_metadata, indent=2))
    print("Selected directions:", json.dumps(selected_metadata, indent=2), flush=True)

    test_path = PROJECT_ROOT / "data" / "workplace_eval" / "input.jsonl"
    test_rows = [json.loads(line) for line in test_path.read_text().splitlines() if line]
    if args.smoke:
        test_rows = test_rows[:5]
    messages = [row["original_text"] for row in test_rows]
    prediction_rows = []
    for alpha in ALPHAS:
        for beta in BETAS:
            started = time.perf_counter()
            generated = generate_batch(
                model=model,
                tokenizer=tokenizer,
                device=device,
                features=features,
                messages=messages,
                alpha=alpha,
                beta=beta,
            )
            latency_ms = (time.perf_counter() - started) * 1000 / len(messages)
            for source, output in zip(test_rows, generated, strict=True):
                prediction_rows.append(
                    {
                        "id": source["id"],
                        "model_name": run_tag,
                        "alpha": alpha,
                        "beta": beta,
                        "original_text": source["original_text"],
                        "generated": output,
                        "latency_ms": round(latency_ms, 2),
                    }
                )
            print(
                f"alpha={alpha:.1f}, beta={beta:.1f} · {latency_ms:.1f} ms/example",
                flush=True,
            )
    predictions = pd.DataFrame(prediction_rows)
    predictions.to_csv(paths["predictions"], index=False)

    if args.skip_learned_metrics:
        toxicity_scorer = similarity_scorer = None
    else:
        toxicity_scorer = DetoxifyToxicityScorer("original", device="cpu")
        similarity_scorer = SentenceTransformerSimilarityScorer(
            "sentence-transformers/all-mpnet-base-v2", device="cpu"
        )
    records = [
        {"original_text": row.original_text, "rewritten_text": row.generated}
        for row in predictions.itertuples(index=False)
    ]
    metrics = evaluate_records(
        records,
        toxicity_scorer=toxicity_scorer,
        similarity_scorer=similarity_scorer,
    )
    evaluated = pd.concat([predictions, pd.DataFrame(metrics)], axis=1)
    baseline = evaluated.query("alpha == 0 and beta == 0").set_index("id")["generated"]
    evaluated["changed_from_00"] = [
        row.generated != baseline.loc[row.id] for row in evaluated.itertuples(index=False)
    ]
    evaluated.to_csv(paths["evaluated"], index=False)

    aggregations = {
        "examples": ("id", "size"),
        "critical_values": ("critical_value_count", "sum"),
        "critical_values_preserved": ("critical_value_preserved_count", "sum"),
        "unsupported_values": ("critical_value_unsupported_count", "sum"),
        "changed_outputs": ("changed_from_00", "sum"),
        "mean_latency_ms": ("latency_ms", "mean"),
    }
    if not args.skip_learned_metrics:
        aggregations.update(
            {
                "mean_input_toxicity": ("toxicity_original", "mean"),
                "mean_output_toxicity": ("toxicity_rewritten", "mean"),
                "mean_semantic_similarity": ("semantic_similarity", "mean"),
            }
        )
    summary = evaluated.groupby(["alpha", "beta"]).agg(**aggregations).reset_index()
    summary["critical_value_recall"] = (
        summary["critical_values_preserved"] / summary["critical_values"].replace(0, np.nan)
    ).fillna(1.0)
    summary["output_change_rate"] = summary["changed_outputs"] / summary["examples"]
    summary.to_csv(paths["summary"], index=False)

    issue_mask = (
        (evaluated["critical_value_missing_count"] > 0)
        | (evaluated["critical_value_unsupported_count"] > 0)
        | evaluated["changed_from_00"]
    )
    review_columns = [
        "id", "alpha", "beta", "original_text", "generated", "changed_from_00",
        "critical_value_missing", "critical_value_unsupported",
    ]
    if not args.skip_learned_metrics:
        review_columns += ["toxicity_rewritten", "semantic_similarity"]
    evaluated.loc[issue_mask, review_columns].to_csv(paths["review"], index=False)
    print("\nSummary\n", summary.round(4).to_string(index=False), flush=True)
    print("\nArtifacts", flush=True)
    for name, path in paths.items():
        print(f"  {name}: {path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--run-tag")
    parser.add_argument("--gyafc-root", type=Path, default=DEFAULT_GYAFC_ROOT)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--extraction-pairs", type=int, default=2_000)
    parser.add_argument("--heldout-pairs", type=int, default=500)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--skip-learned-metrics", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
