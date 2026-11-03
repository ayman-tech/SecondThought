"""CLI for extracting, selecting, and running activation-steering directions."""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import asdict
from pathlib import Path

import torch

from secondthought.steering_experiment import (
    CandidateMetrics,
    SteeringExperiment,
    load_delimited_pairs,
    load_generation_records,
    load_gyafc_pairs,
    load_huggingface_pairs,
    save_artifact,
    stratified_split,
    summarize_outputs,
    surface_diagnostics,
    write_csv,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--model", required=True)
    result.add_argument("--dataset-loader", choices=("gyafc", "file", "huggingface"), required=True)
    result.add_argument("--dataset", required=True, help="GYAFC root, CSV/JSONL path, or HF dataset ID")
    result.add_argument("--source-column", default="source")
    result.add_argument("--target-column", default="target")
    result.add_argument("--group-column")
    result.add_argument("--dataset-config")
    result.add_argument("--dataset-split", default="train")
    result.add_argument("--feature", default="unspecified")
    result.add_argument("--extraction-pairs", type=int, default=8000)
    result.add_argument("--heldout-pairs", type=int, default=2000)
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--batch-size", type=int, default=16)
    result.add_argument("--max-length", type=int, default=128)
    result.add_argument("--device", default="auto")
    result.add_argument("--artifact", type=Path, required=True)
    result.add_argument(
        "--reuse-artifact",
        action="store_true",
        help="Skip extraction/selection and generate from an existing artifact",
    )
    result.add_argument("--candidate-report", type=Path, required=True)
    result.add_argument(
        "--candidate",
        help="Override the artifact's selected candidate for generation",
    )
    result.add_argument("--generation-input", type=Path)
    result.add_argument("--generation-text-column", default="original_text")
    result.add_argument("--generation-id-column", default="id")
    result.add_argument("--generation-output", type=Path)
    result.add_argument("--summary-output", type=Path)
    result.add_argument("--alphas", type=float, nargs="+", default=[1.0, 2.0])
    result.add_argument("--demonstrations", type=int, default=3)
    result.add_argument("--max-new-tokens", type=int, default=64)
    result.add_argument(
        "--instruction",
        default="Rewrite the text while preserving its meaning. Return only the rewrite.",
    )
    return result


def load_pairs(args):
    if args.dataset_loader == "gyafc":
        return load_gyafc_pairs(args.dataset)
    if args.dataset_loader == "file":
        return load_delimited_pairs(
            args.dataset,
            source_column=args.source_column,
            target_column=args.target_column,
            group_column=args.group_column,
        )
    return load_huggingface_pairs(
        args.dataset,
        source_column=args.source_column,
        target_column=args.target_column,
        split=args.dataset_split,
        config_name=args.dataset_config,
        group_column=args.group_column,
    )


def main() -> None:
    args = parser().parse_args()
    if (args.generation_input is None) != (args.generation_output is None):
        raise ValueError("--generation-input and --generation-output must be supplied together")
    if set(args.alphas) - {1.0, 2.0}:
        raise ValueError("This run is constrained to alpha 1 and alpha 2")

    pairs = load_pairs(args)
    extraction, heldout = stratified_split(
        pairs,
        extraction_pairs=args.extraction_pairs,
        heldout_pairs=args.heldout_pairs,
        seed=args.seed,
    )
    print(f"Loaded {len(pairs):,} eligible pairs; extraction={len(extraction):,}, heldout={len(heldout):,}")
    experiment = SteeringExperiment(
        args.model,
        device=args.device,
        max_length=args.max_length,
        batch_size=args.batch_size,
    )
    started = time.perf_counter()
    if args.reuse_artifact:
        artifact = torch.load(args.artifact, map_location="cpu", weights_only=True)
        if artifact["model_id"] != args.model:
            raise ValueError("Artifact model does not match --model")
        directions = artifact["raw_directions"]
        metrics = [CandidateMetrics(**row) for row in artifact["candidates"].values()]
        selected = next(row for row in metrics if row.name == artifact["selected_candidate"])
        print(f"Reused artifact candidate {selected.name}")
    else:
        directions = experiment.extract_directions(extraction)
        print(f"Extracted {len(directions)} candidates in {time.perf_counter() - started:.1f}s")
        metrics = experiment.evaluate_candidates(heldout, directions)
        write_csv(args.candidate_report, [asdict(row) for row in metrics])
        dataset_metadata = {
            "loader": args.dataset_loader,
            "identifier": str(args.dataset),
            "source_column": "informal" if args.dataset_loader == "gyafc" else args.source_column,
            "target_column": "formal" if args.dataset_loader == "gyafc" else args.target_column,
        }
        save_artifact(
            args.artifact,
            model_id=args.model,
            dataset=dataset_metadata,
            feature=args.feature,
            seed=args.seed,
            extraction_pairs=len(extraction),
            heldout_pairs=len(heldout),
            directions=directions,
            metrics=metrics,
        )
        selected = metrics[0]
    if args.candidate:
        try:
            selected = next(row for row in metrics if row.name == args.candidate)
        except StopIteration as error:
            available = ", ".join(sorted(row.name for row in metrics))
            raise ValueError(
                f"Unknown candidate {args.candidate!r}. Available: {available}"
            ) from error
        print(f"Generation candidate override: {selected.name}")
    print("Selected for generation:", json.dumps(asdict(selected), indent=2))

    if args.generation_input:
        records = load_generation_records(args.generation_input, args.generation_text_column)
        demonstrations = random.Random(args.seed).sample(extraction, args.demonstrations)
        vector = directions[selected.name]
        output_rows = []
        for record_index, record in enumerate(records, start=1):
            source = str(record[args.generation_text_column])
            for alpha in args.alphas:
                generated = experiment.generate(
                    source,
                    candidate=selected,
                    vector=vector,
                    alpha=alpha,
                    instruction=args.instruction,
                    demonstrations=demonstrations,
                    max_new_tokens=args.max_new_tokens,
                )
                output_rows.append(
                    {
                        "id": record.get(args.generation_id_column, record_index),
                        "model_id": args.model,
                        "feature": args.feature,
                        "candidate": selected.name,
                        "layer_index": selected.layer_index,
                        "pooling": selected.pooling,
                        "alpha": alpha,
                        "original_text": source,
                        "generated": generated,
                        **surface_diagnostics(source, generated),
                    }
                )
            print(f"Generated {record_index}/{len(records)} records")
        write_csv(args.generation_output, output_rows)
        summary = summarize_outputs(output_rows)
        if args.summary_output:
            write_csv(args.summary_output, summary)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

