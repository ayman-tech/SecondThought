# Reproduce the fluency vectors

Run commands from the repository root after `uv sync --python 3.12 --locked`.
This uses the existing raw-text, target-minus-source mean-difference method.
There is no PCA or new intervention algorithm in this release.

## Dataset preparation

```bash
uv run --locked python -m research.steering_experimentation.prepare_fluency_pairs --download
```

This downloads the original IteraTeR archive from the authors' repository at
commit `41adc0818356f78b362a9382a3732e0529f3fe35` and verifies SHA-256
`386824f3310fca318351c0c76ed6475f99ed85dee0512e0da623af27b35e3ca7`.
An existing archive can be supplied with `--archive /path/to/IteraTeR.zip`.

Only IteraTeR-HUMAN sentence revisions labeled exactly `fluency` are used.
Official training supplies extraction pairs; official development supplies
held-out analysis. The test split is never read. Overlapping documents and
repeated sentences are removed across splits. Filters reject empty/copy pairs,
changed numeric sequences, substantial word-count changes and large edits.
The prepared JSONL and preparation metadata remain in ignored `data/iterater/`.

The current pinned data produces **542 extraction and 84 held-out pairs**,
from 739/115 fluency-labeled train/development rows. The report records every
exclusion count. Labels describe edit intent: they do not prove each revision
improves grammar or preserves meaning. These are document revisions, not a
validated story-continuation dataset. No synthetic examples or
automatically labeled IteraTeR-FULL examples are mixed into this release.

## Extraction

First start the website once to cache its pinned Qwen model, or download that
exact revision with Hugging Face tools. Extraction deliberately uses only cached
weights and does not silently switch model revisions.

```bash
uv run --locked python -m research.steering_experimentation.extract_lab_vectors \
  --feature fluency --device mps --batch-size 8 --max-length 256
```

Use `--device cpu` if MPS is unavailable, or `cuda` with a compatible PyTorch
installation. The model runs in float32, masked pooling in float32, and batch
sums accumulate in float64 on CPU, as in the existing extractor.

Every decoder block output is captured before final model normalization.
Mean pooling excludes padding; final-token pooling uses the last non-padding
token. Each direction averages `revised - original` representations. There are
24 layers × 2 pooling choices = **48 raw vectors**, with no truncated sequences
in the recorded run. The `.pt` artifact and companion report are written to
`research/steering_experimentation/artifacts/lab_v1/`.

The report records provenance, split fingerprints, raw norms, truncation counts,
and held-out projection statistics for each candidate. Layer colours use these
exact held-out scores and Wilson intervals (n=84), not estimates of rewrite quality.
Fluency uses unit-L2 scaling at runtime, matching the existing detoxification
scaling option. Strengths are experimental and uncalibrated; equal alpha values
do not imply equal effects across features or layers.

## Promote and validate

```bash
uv run --locked python -m research.steering_experimentation.promote_lab_catalog
uv run --locked python -m website.api.check_setup
uv run --locked python -m research.steering_experimentation.verify_lab_catalog --device mps
```

Promotion reuses existing formality/detoxification artifacts when absent from
staging. It retains their vector IDs, values, scales and legacy defaults. It
refuses to overwrite an existing artifact with different bytes; intentional
releases with changed extraction need new artifact versions. The catalog now
contains five artifacts and 149 vectors (48 per feature plus five legacy entries).
The hook verification executes all catalog vectors; it is not a quality benchmark.

## Website verification

Restart the website after catalog promotion, then open `/explore`. Fluency is
discovered from the catalog: its checkbox, wheel axis, strength control, both
pooling families, all 24 layers, evidence and run details use the same routing
as the other features. Selecting it does not alter the task or system instruction.

With the server running:

```bash
uv run --locked python -m research.steering_experimentation.verify_multifeature_api \
  --output /tmp/secondthought-multifeature-smoke.json
node website/frontend/tests/browser-smoke.mjs
```

The API smoke checks fluency alone with both poolings, all three features on a
shared layer and independent layers, and baseline restoration. For a quantitative
claim of fluency improvement, a separate generation benchmark with independent
references and human meaning review is still required. Official test examples
must remain separate from extraction and parameter selection.
