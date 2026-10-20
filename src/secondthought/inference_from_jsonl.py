"""Run local CPU rewriting (detoxify, formalize, or both in sequence) and diagnostics on a JSONL dataset."""

from __future__ import annotations

import argparse
import json
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence

from .data import write_csv
from .evaluation import (
    DetoxifyToxicityScorer,
    SentenceTransformerSimilarityScorer,
    evaluate_records,
    format_evaluated_row,
    summarize,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "models/epoch3/t5-small-paradetox"
DEFAULT_ARCHIVE = PROJECT_ROOT / "models/epoch5/epoch3.zip"
# Learned task tokens: each must match the string used in training exactly, trailing space included.
TASK_PREFIXES = {"detoxify": "detoxify: ", "formalize": "formalize: "}
PREFIX = TASK_PREFIXES["detoxify"]
MAX_INPUT_TOKENS = 128


def read_inputs(path: Path) -> list[dict[str, str]]:
    records = []
    seen = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Line {line_number}: invalid JSON") from error
            if not isinstance(record, dict) or any(
                not isinstance(record.get(key), str) or not record[key].strip()
                for key in ("id", "original_text")
            ):
                raise ValueError(f"Line {line_number}: id and original_text must be nonempty strings")
            if record["id"] in seen:
                raise ValueError(f"Line {line_number}: duplicate id {record['id']!r}")
            seen.add(record["id"])
            records.append({key: record[key] for key in ("id", "original_text")})
    if not records:
        raise ValueError("The input dataset is empty")
    return records


def prepare_model(model_dir: Path, archive_path: Path | None = None) -> Path:
    """Extract only the default export, without overwriting an existing folder."""
    model_dir = model_dir.expanduser().resolve()
    if not model_dir.exists() and archive_path is not None:
        if not archive_path.is_file():
            raise FileNotFoundError(f"Missing model {model_dir} and archive {archive_path}")
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=model_dir.parent) as temporary:
            root = Path(temporary)
            expected = root / model_dir.name
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    destination = (root / member.filename).resolve()
                    if not destination.is_relative_to(expected) or stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError(f"Unexpected ZIP member: {member.filename}")
                archive.extractall(root)
            validate_model_files(expected)
            expected.rename(model_dir)
    validate_model_files(model_dir)
    return model_dir


def validate_model_files(model_dir: Path) -> None:
    required = ("config.json", "model.safetensors", "tokenizer_config.json", "tokenizer.json")
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Model folder {model_dir} is missing: {', '.join(missing)}")


def encode_input(tokenizer, record, *, prefix=PREFIX, text=None):
    """Tokenize one record under a task prefix; ``text`` overrides the record's own text (for later stages)."""
    body = record["original_text"] if text is None else text
    encoded = tokenizer(prefix + body.strip(), return_tensors="pt", truncation=False)
    count = encoded["input_ids"].shape[1]
    if count > MAX_INPUT_TOKENS:
        raise ValueError(f"Input {record['id']!r} has {count} tokens; limit is {MAX_INPUT_TOKENS}. Shorten it first.")
    return encoded


def prediction_row(record, rewritten, latency_ms, input_tokens, output_tokens, model_dir, extra=None):
    return {
        **record,
        **(extra or {}),
        "rewritten_text": rewritten,
        "latency_ms": round(latency_ms, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_info": f"local-t5:{model_dir}",
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


def validate_tasks(tasks: Sequence[str]) -> tuple[str, ...]:
    tasks = tuple(tasks)
    if not tasks:
        raise ValueError("At least one task is required")
    unknown = [task for task in tasks if task not in TASK_PREFIXES]
    if unknown:
        raise ValueError(f"Unknown task {unknown[0]!r}; choose from {', '.join(TASK_PREFIXES)}")
    if len(set(tasks)) != len(tasks):
        raise ValueError("Each task may appear only once in a pipeline")
    return tasks


def run(
    dataset: Path,
    output: Path,
    model_dir: Path | None = None,
    *,
    include_learned_metrics: bool = True,
    toxicity_model: str = "original",
    similarity_model: str = "sentence-transformers/all-mpnet-base-v2",
    device: str = "cpu",
    tasks: Sequence[str] = ("detoxify",),
) -> None:
    tasks = validate_tasks(tasks)
    records = read_inputs(dataset)
    selected = prepare_model(
        model_dir if model_dir is not None else DEFAULT_MODEL,
        DEFAULT_ARCHIVE if model_dir is None else None,
    )
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(selected, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(selected, local_files_only=True).to("cpu")
    model.eval()
    # Validate every input before generating anything or replacing an output file. Only the first
    # stage can be checked up front; later stages read the previous stage's output.
    for record in records:
        encode_input(tokenizer, record, prefix=TASK_PREFIXES[tasks[0]])
    print(
        f"Loaded {selected}; processing {len(records)} messages on CPU "
        f"with pipeline {' > '.join(tasks)}.",
        flush=True,
    )
    predictions = []
    with torch.inference_mode():
        for index, record in enumerate(records, 1):
            started = perf_counter()
            text = record["original_text"]
            stage_texts = {}
            first_input_tokens = None
            for stage, task in enumerate(tasks):
                inputs = encode_input(tokenizer, record, prefix=TASK_PREFIXES[task], text=text)
                if first_input_tokens is None:
                    first_input_tokens = inputs["input_ids"].shape[1]
                generated = model.generate(**inputs, max_new_tokens=128, num_beams=4, do_sample=False)
                text = tokenizer.decode(generated[0], skip_special_tokens=True).strip()
                if not text:
                    raise ValueError(f"Model produced an empty {task} rewrite for {record['id']!r}")
                if stage < len(tasks) - 1:
                    stage_texts[f"after_{task}"] = text
            rewritten = text
            elapsed_ms = (perf_counter() - started) * 1000
            # Exclude the decoder's initial token and padding; include generated EOS.
            output_tokens = sum(token != tokenizer.pad_token_id for token in generated[0, 1:].tolist())
            extra = {"pipeline": " > ".join(tasks), **stage_texts}
            predictions.append(prediction_row(
                record, rewritten, elapsed_ms, first_input_tokens, output_tokens, selected, extra,
            ))
            print(f"[{index}/{len(records)}] {record['id']}", flush=True)
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
    rows = [
        format_evaluated_row(prediction, metrics)
        for prediction, metrics in zip(predictions, metric_rows, strict=True)
    ]
    write_csv(output, rows)
    summary = summarize(metric_rows)
    summary["average_latency_ms"] = round(
        sum(row["latency_ms"] for row in predictions) / len(predictions), 2
    )
    print(json.dumps(summary, indent=2))
    print(f"Saved {len(rows)} rows to {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "data/workplace_eval/input.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "outputs/epoch3_evaluated.csv")
    parser.add_argument("--model-dir", type=Path, help="Extracted local model folder; skips default ZIP extraction")
    parser.add_argument(
        "--without-learned-metrics",
        action="store_true",
        help="skip Detoxify and Sentence-Transformers evaluation",
    )
    parser.add_argument("--toxicity-model", default="original")
    parser.add_argument(
        "--similarity-model", default="sentence-transformers/all-mpnet-base-v2"
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["detoxify"],
        metavar="TASK",
        help=f"Task prefixes to apply in order ({', '.join(TASK_PREFIXES)}); "
        "e.g. '--tasks detoxify formalize' feeds each stage's output into the next",
    )
    args = parser.parse_args()
    try:
        run(
            args.dataset,
            args.output,
            args.model_dir,
            include_learned_metrics=not args.without_learned_metrics,
            toxicity_model=args.toxicity_model,
            similarity_model=args.similarity_model,
            device=args.device,
            tasks=args.tasks,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
