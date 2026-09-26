"""Command-line entry points for rewriting, batch generation, and evaluation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .config import Settings, load_settings
from .data import read_csv, read_jsonl, write_csv
from .evaluation import evaluate_pair, summarize
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
        predictions.append({"id": example["id"], **asdict(result)})
        print(f"completed {example['id']}")
    write_csv(output_path, predictions)


def run_evaluation(predictions_path: str, output_path: str) -> None:
    predictions = read_csv(predictions_path)
    evaluated_rows = []
    metric_rows = []
    for prediction in predictions:
        metrics = evaluate_pair(
            prediction["original_text"], prediction["rewritten_text"]
        )
        metric_rows.append(metrics)
        ending = {
            key: prediction[key]
            for key in ("model_info", "timestamp_utc")
            if key in prediction
        }
        main_columns = {
            key: value
            for key, value in prediction.items()
            if key not in ending
        }
        evaluated_rows.append({**main_columns, **metrics, **ending})

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
    return root


def main() -> None:
    args = parser().parse_args()
    settings = load_settings(args.config)
    if args.command == "rewrite":
        print(build_rewriter(settings).rewrite(args.message).rewritten_text)
    elif args.command == "batch":
        run_batch(args.dataset, args.output, settings)
    elif args.command == "evaluate":
        run_evaluation(args.predictions, args.output)


if __name__ == "__main__":
    main()
