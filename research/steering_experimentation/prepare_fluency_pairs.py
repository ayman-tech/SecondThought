"""Prepare original IteraTeR-HUMAN fluency pairs; never consume its test split.

The archive is pinned and checked. Raw sentences stay in ignored local files.
Labels identify revision intent, not independently verified quality improvement.
"""
from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REVISION = "41adc0818356f78b362a9382a3732e0529f3fe35"
URL = f"https://raw.githubusercontent.com/vipulraheja/iterater/{REVISION}/dataset/IteraTeR.zip"
SHA256 = "386824f3310fca318351c0c76ed6475f99ed85dee0512e0da623af27b35e3ca7"


def normalized(text):
    return " ".join(text.split()).casefold()


def exclusion(row):
    if row.get("labels") != "fluency":
        return "other_intent"
    source, target = row["before_sent"].strip(), row["after_sent"].strip()
    if not source or not target or normalized(source) == normalized(target):
        return "empty_or_copy"
    if len(source.split()) < 3 or len(target.split()) < 3:
        return "too_short"
    if not 0.8 <= len(target.split()) / len(source.split()) <= 1.25:
        return "length_change"
    if re.findall(r"\d+(?:[.,]\d+)*", source) != re.findall(r"\d+(?:[.,]\d+)*", target):
        return "number_change"
    if SequenceMatcher(None, normalized(source), normalized(target), autojunk=False).ratio() < 0.8:
        return "large_edit"
    return None


def prepare(archive: Path, output: Path):
    payload = archive.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError("IteraTeR archive checksum mismatch")
    counts = Counter()
    rows_by_split = {}
    with zipfile.ZipFile(archive) as bundle:
        for split in ("train", "dev"):
            name = f"IteraTeR/human_sent_level/{split}.json"
            rows_by_split[split] = [json.loads(line) for line in bundle.read(name).splitlines() if line.strip()]
    # Exclude any training document that also occurs in official development.
    dev_docs = {str(row["doc_id"]) for row in rows_by_split["dev"]}
    seen_texts, records = set(), []
    # Give the held-out split priority when duplicate sentences cross documents.
    for original, split in (("dev", "heldout"), ("train", "extraction")):
        for index, row in enumerate(rows_by_split[original]):
            counts[f"{original}_input"] += 1
            reason = exclusion(row)
            if reason is None and original == "train" and str(row["doc_id"]) in dev_docs:
                reason = "document_overlap"
            texts = {normalized(row["before_sent"]), normalized(row["after_sent"])}
            if reason is None and texts & seen_texts:
                reason = "duplicate_sentence"
            if reason:
                counts[f"{original}_excluded_{reason}"] += 1
                continue
            seen_texts.update(texts)
            counts[f"{original}_retained"] += 1
            records.append(dict(source=row["before_sent"].strip(), target=row["after_sent"].strip(),
                group=str(row["doc_id"]), row_id=f"human/{original}:{index}", split=split))
    if not all(any(row["split"] == split for row in records) for split in ("extraction", "heldout")):
        raise ValueError("No pairs retained for one or both splits")
    report = dict(dataset="IteraTeR-HUMAN", dataset_revision=REVISION, archive_url=URL,
        archive_sha256=SHA256, annotation="human revision intent: fluency",
        orientation="revised_minus_original", counts=dict(counts),
        split_policy="official train/dev; exclude overlapping documents and any repeated source/target sentence; test untouched",
        filters=dict(min_words=3, word_length_ratio=[0.8, 1.25], minimum_character_similarity=0.8,
                     preserve_numeric_sequence=True, exact_intent="fluency"),
        limitations="Intent labels and lexical filters do not guarantee improvement or semantic equivalence. Human document revisions; transfer to continuation is unestablished.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
    temporary.replace(output)
    report["pairs_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".metadata.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return records, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/iterater/IteraTeR.zip")
    parser.add_argument("--download", action="store_true", help="Download the pinned official archive if missing")
    parser.add_argument("--output", type=Path, default=ROOT / "data/iterater/fluency_pairs.jsonl")
    args = parser.parse_args()
    if args.download and not args.archive.exists():
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(URL, timeout=120) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != SHA256:
            raise ValueError("Downloaded archive checksum mismatch")
        args.archive.write_bytes(payload)
    prepare(args.archive, args.output)


if __name__ == "__main__":
    main()
