"""Add formality columns to an already-evaluated CSV, writing a new file.

    python -m secondthought.add_formality <input.csv> <output.csv> [--device cpu] [--no-model]
        [--original-column original_text] [--rewritten-column rewritten_text]

The input is only read. Every input column is kept, with its value and position;
the formality columns are inserted right after the last existing metric column
(or after the text columns if the file has no metrics). The steering artifacts
use other text column names: --original-column toxic --rewritten-column generated.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .data import read_csv, write_csv
from evaluation.evaluation import EVALUATION_COLUMNS
from .formality_evaluation import (
    FORMALITY_COLUMNS,
    RobertaFormalityScorer,
    evaluate_formality_records,
    summarize_formality,
)


def insert_after_metrics(row: Mapping[str, Any], formality: Mapping[str, Any], text_columns: tuple[str, ...]) -> dict:
    """Keep the row exactly as it is; put the formality columns after its last metric column."""
    keys = [key for key in row if key not in FORMALITY_COLUMNS]
    anchors = [i for i, key in enumerate(keys) if key in EVALUATION_COLUMNS] or [
        i for i, key in enumerate(keys) if key in ("id", *text_columns)]
    cut = anchors[-1] + 1 if anchors else len(keys)
    return {**{k: row[k] for k in keys[:cut]}, **formality, **{k: row[k] for k in keys[cut:]}}


def add_formality(
    input_path: Path,
    output_path: Path,
    *,
    device: str = "cpu",
    use_model: bool = True,
    original_column: str = "original_text",
    rewritten_column: str = "rewritten_text",
) -> dict:
    if output_path.resolve() == input_path.resolve():
        raise SystemExit("output must be a different file from the input")
    if output_path.exists():
        raise SystemExit(f"{output_path} already exists; refusing to overwrite it")
    rows = read_csv(input_path)
    if not rows or not {original_column, rewritten_column} <= set(rows[0]):
        raise SystemExit(f"{input_path} needs {original_column} and {rewritten_column} columns")
    records = [{"original_text": row[original_column], "rewritten_text": row[rewritten_column]} for row in rows]
    scorer = RobertaFormalityScorer(device=device) if use_model else None
    results = evaluate_formality_records(records, formality_scorer=scorer)
    text_columns = (original_column, rewritten_column)
    write_csv(output_path, [insert_after_metrics(row, result, text_columns) for row, result in zip(rows, results, strict=True)])
    return summarize_formality(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add formality columns to an evaluated CSV.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--no-model", action="store_true", help="register markers only, no model download")
    parser.add_argument("--original-column", default="original_text")
    parser.add_argument("--rewritten-column", default="rewritten_text")
    args = parser.parse_args()
    summary = add_formality(
        args.input, args.output, device=args.device, use_model=not args.no_model,
        original_column=args.original_column, rewritten_column=args.rewritten_column,
    )
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
