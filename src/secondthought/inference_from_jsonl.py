"""Run local CPU detoxification and existing diagnostics on a JSONL dataset."""

from __future__ import annotations

import argparse
import json
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .data import write_csv
from .evaluation import evaluate_pair, summarize

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "models/epoch3/t5-small-paradetox"
DEFAULT_ARCHIVE = PROJECT_ROOT / "models/epoch5/epoch3.zip"
PREFIX = "detoxify: "
MAX_INPUT_TOKENS = 128
COLUMNS = (
    "id", "original_text", "rewritten_text", "latency_ms", "input_tokens",
    "output_tokens", "response_id", "number_recall", "word_overlap",
    "edit_ratio", "length_ratio", "exact_match", "model_info", "timestamp_utc",
)


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


def encode_input(tokenizer, record):
    encoded = tokenizer(PREFIX + record["original_text"].strip(), return_tensors="pt", truncation=False)
    count = encoded["input_ids"].shape[1]
    if count > MAX_INPUT_TOKENS:
        raise ValueError(f"Input {record['id']!r} has {count} tokens; limit is {MAX_INPUT_TOKENS}. Shorten it first.")
    return encoded


def evaluated_row(record, rewritten, latency_ms, input_tokens, output_tokens, model_dir):
    row = {
        **record,
        "rewritten_text": rewritten,
        "latency_ms": round(latency_ms, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "response_id": "",  # Local inference has no API response ID.
        **evaluate_pair(record["original_text"], rewritten),
        "model_info": f"local-t5:{model_dir}",
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }
    return {column: row[column] for column in COLUMNS}


def run(dataset: Path, output: Path, model_dir: Path | None = None) -> None:
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
    # Validate every input before generating anything or replacing an output file.
    for record in records:
        encode_input(tokenizer, record)
    print(f"Loaded {selected}; processing {len(records)} messages on CPU.", flush=True)
    rows = []
    with torch.inference_mode():
        for index, record in enumerate(records, 1):
            started = perf_counter()
            inputs = encode_input(tokenizer, record)
            generated = model.generate(**inputs, max_new_tokens=128, num_beams=4, do_sample=False)
            rewritten = tokenizer.decode(generated[0], skip_special_tokens=True).strip()
            elapsed_ms = (perf_counter() - started) * 1000
            if not rewritten:
                raise ValueError(f"Model produced an empty rewrite for {record['id']!r}")
            # Exclude the decoder's initial token and padding; include generated EOS.
            output_tokens = sum(token != tokenizer.pad_token_id for token in generated[0, 1:].tolist())
            rows.append(evaluated_row(
                record, rewritten, elapsed_ms, inputs["input_ids"].shape[1], output_tokens, selected,
            ))
            print(f"[{index}/{len(records)}] {record['id']}", flush=True)
    write_csv(output, rows)
    summary = summarize(rows)
    summary["average_latency_ms"] = round(sum(row["latency_ms"] for row in rows) / len(rows), 2)
    print(json.dumps(summary, indent=2))
    print(f"Saved {len(rows)} rows to {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "data/workplace_eval/input.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "outputs/epoch3_evaluated.csv")
    parser.add_argument("--model-dir", type=Path, help="Extracted local model folder; skips default ZIP extraction")
    args = parser.parse_args()
    try:
        run(args.dataset, args.output, args.model_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
