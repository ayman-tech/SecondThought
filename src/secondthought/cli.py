"""Command-line entry points for rewriting, batch generation, and evaluation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .config import Settings, load_settings
from .data import read_csv, read_jsonl, write_csv
from .evaluation import (
    DetoxifyToxicityScorer,
    SentenceTransformerSimilarityScorer,
    evaluate_records,
    format_evaluated_row,
    summarize,
)
from .rewriter import OpenAIRewriter


def build_rewriter(settings: Settings) -> OpenAIRewriter:
    return OpenAIRewriter(
        model=settings.model,
        prompt_path=settings.prompt_path,
        max_output_tokens=settings.max_output_tokens,
    )


def run_batch(dataset_path: str, output_path: str, settings: Settings) -> None:
    rewriter = build_rewriter(settings)
    predictions = []
    for example in read_jsonl(dataset_path):
        result = rewriter.rewrite(example["original_text"])
        prediction = {"id": example["id"], **asdict(result)}
        if "critical_values" in example:
            prediction["critical_values"] = json.dumps(
                example["critical_values"], ensure_ascii=False
            )
        predictions.append(prediction)
        print(f"completed {example['id']}")
    write_csv(output_path, predictions)


def run_evaluation(
    predictions_path: str,
    output_path: str,
    *,
    include_learned_metrics: bool = False,
    toxicity_model: str = "original",
    similarity_model: str = "sentence-transformers/all-mpnet-base-v2",
    device: str = "cpu",
) -> None:
    predictions = read_csv(predictions_path)
    metric_rows = evaluate_records(
        predictions,
        toxicity_scorer=(
            DetoxifyToxicityScorer(toxicity_model, device=device)
            if include_learned_metrics
            else None
        ),
        similarity_scorer=(
            SentenceTransformerSimilarityScorer(similarity_model, device=device)
            if include_learned_metrics
            else None
        ),
    )
    evaluated_rows = [
        format_evaluated_row(prediction, metrics)
        for prediction, metrics in zip(predictions, metric_rows, strict=True)
    ]

    write_csv(output_path, evaluated_rows)
    summary = summarize(metric_rows)
    if predictions:
        summary["average_latency_ms"] = round(
            sum(float(row["latency_ms"]) for row in predictions) / len(predictions), 2
        )
    print(json.dumps(summary, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="SecondThought baseline tools")
    root.add_argument("--config", default="config/default.toml")
    commands = root.add_subparsers(dest="command", required=True)

    rewrite = commands.add_parser("rewrite", help="Rewrite one message")
    rewrite.add_argument("message")

    batch = commands.add_parser("batch", help="Generate predictions for JSONL data")
    batch.add_argument("--dataset", required=True)
    batch.add_argument("--output", required=True)

    evaluate = commands.add_parser("evaluate", help="Add metrics to a prediction CSV")
    evaluate.add_argument("--predictions", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument(
        "--with-learned-metrics",
        action="store_true",
        help="run Detoxify toxicity and Sentence-Transformers similarity",
    )
    evaluate.add_argument("--toxicity-model", default="original")
    evaluate.add_argument(
        "--similarity-model", default="sentence-transformers/all-mpnet-base-v2"
    )
    evaluate.add_argument("--device", default="cpu")
    return root


def main() -> None:
    args = parser().parse_args()
    settings = load_settings(args.config)
    if args.command == "rewrite":
        print(build_rewriter(settings).rewrite(args.message).rewritten_text)
    elif args.command == "batch":
        run_batch(args.dataset, args.output, settings)
    elif args.command == "evaluate":
        run_evaluation(
            args.predictions,
            args.output,
            include_learned_metrics=args.with_learned_metrics,
            toxicity_model=args.toxicity_model,
            similarity_model=args.similarity_model,
            device=args.device,
        )


if __name__ == "__main__":
    main()
