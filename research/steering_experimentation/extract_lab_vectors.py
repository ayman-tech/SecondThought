"""Extract Qwen lab features at every decoder output, with held-out reports.

Uses local datasets and a pinned cached model snapshot. Writes research artifacts
only; promotion into the runtime catalog is a separate validated operation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import torch
import transformers
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

from secondthought.lab.extraction import POOLINGS, SITE, capture_representations
from research.steering_experimentation.feature_recipes import FEATURES

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Pair:
    source: str
    target: str
    group: str
    row_id: str


def normalized(text):
    return " ".join(text.split()).casefold()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def split_digest(pairs):
    return digest(json.dumps([(p.row_id, p.source, p.target) for p in pairs],
                             ensure_ascii=False, separators=(",", ":")).encode())


def load_formality(root, seed):
    rng = random.Random(seed)
    pairs, files = [], {}
    for domain in ("Entertainment_Music", "Family_Relationships"):
        source_path, target_path = root / domain / "train/informal", root / domain / "train/formal"
        sources, targets = source_path.read_text().splitlines(), target_path.read_text().splitlines()
        if len(sources) != len(targets):
            raise ValueError("GYAFC source/target files are not aligned")
        for path in (source_path, target_path):
            files[str(path.relative_to(root))] = digest(path.read_bytes())
        pairs.extend(Pair(s.strip(), t.strip(), domain, f"{domain}:{i}")
                     for i, (s, t) in enumerate(zip(sources, targets, strict=True))
                     if normalized(s) and normalized(t) and normalized(s) != normalized(t))
    rng.shuffle(pairs)
    seen, unique = set(), []
    for pair in pairs:
        key = normalized(pair.source)
        if key not in seen:
            seen.add(key)
            unique.append(pair)
    extraction, heldout = [], []
    for domain in ("Entertainment_Music", "Family_Relationships"):
        rows = [p for p in unique if p.group == domain]
        if len(rows) < 5000:
            raise ValueError("Need 5,000 unique sources per GYAFC domain")
        extraction.extend(rows[:4000])
        heldout.extend(rows[4000:5000])
    rng.shuffle(extraction)
    rng.shuffle(heldout)
    return extraction, heldout, dict(dataset="GYAFC", input_checksums=files,
        split_policy="seeded source-deduplicated balanced domains; 4000/1000 per domain",
        orientation="formal_minus_informal")


def load_detox(path):
    groups = {"extraction": [], "heldout": []}
    with path.open() as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            groups[row["split"]].append(Pair(row["toxic"], row["neutral"], "paradetox", str(index)))
    return groups["extraction"], groups["heldout"], dict(dataset="s-nlp/paradetox",
        input_sha256=digest(path.read_bytes()), split_policy="existing notebook CSV split, unchanged",
        orientation="neutral_minus_toxic")


def load_prepared_pairs(path, feature=None):
    metadata = json.loads(path.with_suffix('.metadata.json').read_text())
    if feature is not None and metadata.get('feature') != feature:
        raise ValueError('Prepared pairs belong to a different feature')
    if metadata.get('pairs_sha256') != digest(path.read_bytes()):
        raise ValueError('Prepared pairs checksum mismatch')
    groups = {'extraction': [], 'heldout': []}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        groups[row['split']].append(Pair(row['source'], row['target'], row['group'], row['row_id']))
    extraction, heldout = groups['extraction'], groups['heldout']
    if {p.group for p in extraction} & {p.group for p in heldout}:
        raise ValueError('Prepared pair groups must be disjoint')
    extraction_texts = {normalized(t) for p in extraction for t in (p.source, p.target)}
    heldout_texts = {normalized(t) for p in heldout for t in (p.source, p.target)}
    if extraction_texts & heldout_texts:
        raise ValueError('Prepared source/target sentences must not cross splits')
    return extraction, heldout, metadata


def load_fluency(path):
    return load_prepared_pairs(path)


def validate_split(extraction, heldout, expected=None):
    if len(extraction) < 2 or len(heldout) < 2:
        raise ValueError('Need at least two extraction and held-out pairs')
    if expected is not None and (len(extraction), len(heldout)) != expected:
        raise ValueError(f'Expected {expected} extraction/held-out pairs')
    left, right = {normalized(p.source) for p in extraction}, {normalized(p.source) for p in heldout}
    if len(left) != len(extraction) or len(right) != len(heldout) or not left.isdisjoint(right):
        raise ValueError("Extraction and held-out sources must be unique and disjoint")
    if any(not normalized(p.source) or not normalized(p.target) or normalized(p.source) == normalized(p.target)
           for p in [*extraction, *heldout]):
        raise ValueError("Empty or exact-copy pair")


def representations(model, tokenizer, rows, device, max_length, truncation_counts):
    texts = [p.source for p in rows] + [p.target for p in rows]
    lengths = tokenizer(texts, padding=False, truncation=False)["input_ids"]
    truncation_counts.update({"sequences": len(texts), "truncated": sum(len(x) > max_length for x in lengths)})
    inputs = tokenizer(texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    reps = capture_representations(model.model, model.model.layers, inputs)
    size = len(rows)
    return reps[:, size:] - reps[:, :size]


def extract(model, tokenizer, feature, extraction, heldout, metadata, args, device):
    count = model.config.num_hidden_layers
    shape = (2, count, model.config.hidden_size)
    sums = torch.zeros(shape, dtype=torch.float64)
    truncated = Counter()
    started = time.monotonic()
    for start in range(0, len(extraction), args.batch_size):
        batch = extraction[start:start + args.batch_size]
        deltas = representations(model, tokenizer, batch, device, args.max_length, truncated)
        sums += deltas.sum(1).cpu().double()
        stop = start + len(batch)
        if start == 0 or stop % (args.batch_size * 10) == 0 or stop == len(extraction):
            print(f"{feature} extraction {stop}/{len(extraction)} pairs; {time.monotonic()-started:.1f}s", flush=True)
    directions = (sums / len(extraction)).float()
    norms = directions.norm(dim=-1)
    if not torch.isfinite(directions).all() or not (norms > 0).all():
        raise ValueError("Non-finite or zero extracted direction")
    units = (directions / norms.unsqueeze(-1)).to(device)
    projections = []
    heldout_truncated = Counter()
    for start in range(0, len(heldout), args.batch_size):
        batch = heldout[start:start + args.batch_size]
        deltas = representations(model, tokenizer, batch, device, args.max_length, heldout_truncated)
        projections.append((deltas * units.unsqueeze(1)).sum(-1).cpu())
        stop = start + len(batch)
        if start == 0 or stop % (args.batch_size * 10) == 0 or stop == len(heldout):
            print(f"{feature} heldout {stop}/{len(heldout)} pairs; {time.monotonic()-started:.1f}s", flush=True)
    projections = torch.cat(projections, dim=1)
    candidates, vectors = {}, {}
    for pooling_index, pooling in enumerate(POOLINGS):
        for index in range(count):
            name = f"layer{index}_{pooling}"
            gaps = projections[pooling_index, :, index]
            mean, std = float(gaps.mean()), float(gaps.std(unbiased=True))
            candidates[name] = dict(layer_index=index, pooling=pooling, site=SITE,
                raw_direction_norm=float(norms[pooling_index, index]),
                heldout_pairs=len(heldout), heldout_ordering_accuracy=float((gaps > 0).float().mean()),
                heldout_mean_projection=mean, heldout_projection_std=std,
                heldout_effect_size=mean/std if std else None, behavioral_status="experimental")
            vectors[name] = directions[pooling_index, index].contiguous()
    artifact = dict(format_version=1, model_id=MODEL, model_revision=REVISION,
        tokenizer_revision=REVISION, feature=feature, site=SITE,
        layer_count=count, hidden_size=model.config.hidden_size,
        candidates=candidates, raw_directions=vectors,
        provenance=dict(**metadata, seed=args.seed, extraction_pairs=len(extraction), heldout_pairs=len(heldout),
            extraction_split_sha256=split_digest(extraction), heldout_split_sha256=split_digest(heldout),
            extraction_groups=dict(Counter(p.group for p in extraction)),
            heldout_groups=dict(Counter(p.group for p in heldout)), input_format="raw text, no chat template",
            max_length=args.max_length, padding_side="right", pooling_precision="float32",
            extraction_batch_size=args.batch_size, estimator="paired_mean_difference",
            accumulation_precision="float64 across batch sums", model_precision="float32", device=str(device),
            torch_version=str(torch.__version__), transformers_version=transformers.__version__,
            python_version=platform.python_version(), extraction_truncation=dict(truncated),
            heldout_truncation=dict(heldout_truncated), extraction_code_sha256=digest(Path(__file__).read_bytes()),
            capture_code_sha256=digest((ROOT/'src/secondthought/lab/extraction.py').read_bytes()),
            elapsed_seconds=round(time.monotonic()-started, 2)))
    args.output.mkdir(parents=True, exist_ok=True)
    version=getattr(args,'artifact_version','v1')
    path = args.output / f"qwen2_5_0_5b_{feature}_all_layers_{version}.pt"
    if path.exists():raise ValueError('Artifact already exists; use a new output directory or artifact version')
    temporary = path.with_suffix('.pt.tmp')
    torch.save(artifact, temporary)
    temporary.replace(path)
    report = path.with_suffix('.json')
    report.write_text(json.dumps({key: value for key, value in artifact.items() if key != 'raw_directions'}, indent=2) + '\n')
    print(f"Saved {path}: {len(vectors)} vectors; sha256={digest(path.read_bytes())}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gyafc', type=Path)
    parser.add_argument('--fluency-pairs', type=Path, default=ROOT/'data/iterater/fluency_pairs.jsonl')
    parser.add_argument('--pairs-dir', type=Path, default=ROOT/'data/lab_features')
    parser.add_argument('--prepared-pairs',type=Path,help='Explicit prepared dataset, including synthetic features')
    parser.add_argument('--feature-id',help='Feature ID for an explicit prepared dataset')
    parser.add_argument('--artifact-version',default='v1')
    parser.add_argument('--features', nargs='+', choices=list(FEATURES))
    parser.add_argument('--paradetox', type=Path, default=ROOT/'research/steering_experimentation/artifacts/paradetox_direction_pairs.csv')
    parser.add_argument('--output', type=Path, default=ROOT/'research/steering_experimentation/artifacts/lab_v1')
    parser.add_argument('--device', choices=['mps','cpu','cuda'], default='mps')
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--max-length', type=int, default=128)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--feature', choices=[*FEATURES, 'both', 'all'], default='both',
                        help='both preserves the original formality/detoxification workflow')
    args = parser.parse_args()
    if args.batch_size < 1 or args.max_length < 1:
        parser.error('Batch size and max length must be positive')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',args.artifact_version):parser.error('Invalid artifact version')
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    splits = {}
    selected = args.features or (list(FEATURES) if args.feature=='all' else
        ['formality','detoxification'] if args.feature=='both' else [args.feature])
    if args.prepared_pairs:
        if args.features:parser.error('Use --feature-id with --prepared-pairs, not --features')
        metadata=json.loads(args.prepared_pairs.with_suffix('.metadata.json').read_text())
        feature=args.feature_id or metadata.get('feature','')
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}',feature):parser.error('Invalid prepared feature ID')
        splits[feature]=load_prepared_pairs(args.prepared_pairs,feature)
        selected=[]
    elif args.feature_id:parser.error('--feature-id requires --prepared-pairs')
    if 'formality' in selected:
        if args.gyafc is None:
            parser.error('--gyafc is required when extracting formality')
        splits['formality'] = load_formality(args.gyafc, args.seed)
    if 'detoxification' in selected:
        splits['detoxification'] = load_detox(args.paradetox)
    if 'fluency' in selected:
        splits['fluency'] = load_fluency(args.fluency_pairs)
    for feature in selected:
        if feature not in ('formality','detoxification','fluency'):
            splits[feature] = load_prepared_pairs(args.pairs_dir/(feature+'_pairs.jsonl'),feature)
    for feature, (extraction, heldout, _) in splits.items():
        validate_split(extraction, heldout, (8000, 2000) if feature in ('formality','detoxification') and not args.prepared_pairs else None)
        print(f'{feature}: validated {len(extraction)}/{len(heldout)} unique, disjoint source pairs', flush=True)
    snapshot = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(snapshot)
    tokenizer.padding_side = 'right'
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(snapshot, dtype=torch.float32).to(device).eval()
    model.requires_grad_(False)
    print(f'Loaded pinned {MODEL}@{REVISION}, {len(model.model.layers)} layers on {device}', flush=True)
    for feature, (extraction, heldout, metadata) in splits.items():
        target=args.output/f'qwen2_5_0_5b_{feature}_all_layers_{args.artifact_version}.pt'
        if target.exists():raise ValueError('Artifact already exists; use a new output directory or version')
        extract(model, tokenizer, feature, extraction, heldout, metadata, args, device)


if __name__ == '__main__':
    main()
