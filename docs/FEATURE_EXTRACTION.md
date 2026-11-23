# Seven-feature steering pipeline

The Qwen catalog now has seven features, 24 decoder blocks and two pooling
choices per feature: **336 experimental vectors plus five legacy references**,
in nine checked artifacts. Extraction still uses raw-text target-minus-source
mean differences. PCA, other estimators, and new intervention algorithms are
not part of this release. Existing vectors and compatibility defaults are preserved.

See the [integration review](STEERING_INTEGRATION_REVIEW.md) for the subsequent
per-feature audit, known data-quality issues and exact frontend/colour checks.

## Phase 1: sources and pair preparation

| Feature | Source | Pair construction | Extraction / held-out |
| --- | --- | --- | --- |
| Simplification | WikiLarge training data, mirror linked by DRESS authors | Aligned complex → simple sentences | 2,000 / 500 |
| Conciseness | Google sentence-compression `train01` | Original → compressed news sentence | 2,000 / 500 |
| Empathy | EPITOME Reddit emotional reactions | Same response with exact annotated empathy spans removed → original response | 417 / 105 |
| Politeness | Tag-and-Generate training-ready corpus, train split, P_8/P_9 | Same request with standalone `please` removed → original | 2,000 / 500 |

Empathy and politeness are **derived ablation contrasts**, not human-rated
parallel rewrites. Empathy targets emotional acknowledgment; it does not establish
general empathy or mental-health competence. Politeness targets courtesy-marker
wording rather than every aspect of politeness. Span removal can affect grammar.
These limitations are exposed under **Dataset & direction** in the website.

Preparation pins source revisions/content hashes, excludes empty/copy/short/long
pairs and changed numeric sequences, and applies additional feature-specific
filters. Simplification/compression retain conservative edit and length ratios;
explicit negations cannot simply disappear. Original datasets can still contain
misalignments or omit facts. No lexical filter proves semantic equivalence.

Splits use seeded connected groups: a shared document/context ID, or a sentence
appearing on either side of multiple pairs, keeps those pairs in one partition.
WikiLarge and the training-ready politeness archive do not provide document IDs;
we isolate connected sentence variants and do not claim document-level separation
for them. Prepared pairs keep unique sources. Groups exposed in metadata are
hashes, not post text or source URLs. ASSET, compression evaluation files and the
curated politeness test set are not consumed.

```bash
uv run --locked python -m research.steering_experimentation.prepare_feature_pairs --download
```

This downloads about 140 MB of compressed source data under ignored
`data/feature_sources/`, and writes ignored JSONL/metadata under
`data/lab_features/`. Use `--features empathy politeness` to prepare a subset.
Every source is checksum-verified. The mutable authors-linked Drive download is
accepted only if its content matches the pinned hash; a changed file requires an
explicit source/version update. No automatic fallback to an unverified mirror.

Source attribution and access:

- [WikiLarge / DRESS](https://github.com/XingxingZhang/dress), using the
  [authors-linked mirror](https://github.com/louismartin/dress-data).
- [Google sentence compression](https://github.com/google-research-datasets/sentence-compression).
- [EPITOME](https://github.com/behavioral-data/Empathy-Mental-Health), Sharma,
  Miner, Atkins and Althoff (EMNLP 2020), University of Washington. The attribution
  license notice is retained in [licenses/EPITOME_ATTRIBUTION.txt](licenses/EPITOME_ATTRIBUTION.txt),
  and the lab acknowledges the authors. No TalkLife data is used.
- [Politeness Transfer](https://github.com/tag-and-generate/politeness-dataset),
  Madaan et al. (ACL 2020). Original email content stays local. Repository code
  licenses should not be represented as a blanket license over underlying emails.

## Phase 2: extract and analyze all layers

After the pinned Qwen model is cached:

```bash
uv run --locked python -m research.steering_experimentation.extract_lab_vectors \
  --features simplification conciseness empathy politeness \
  --device mps --batch-size 8 --max-length 256
```

CPU is supported with `--device cpu`. Capture uses every decoder block output
before final model normalization. Mean pooling excludes padding; final-token
pooling uses the last non-padding token. Model/pooling are float32, batch totals
accumulate in float64, and stored directions are float32. All four recorded runs
had zero truncation. Each artifact has 48 candidates, split fingerprints, raw
norms, held-out projections and provenance. Unit-L2 runtime scaling is declared
in the shared feature recipe; strengths remain uncalibrated.

Observed held-out pair-ordering ranges across the 24 layers:

| Feature | Mean pooling | Final token |
| --- | --- | --- |
| Simplification | 70.2–81.0% | 69.6–82.6% |
| Conciseness | 98.2–100% | 91.8–100% |
| Empathy | 93.3–100% | 86.7–92.4% |
| Politeness | 94.8–100% | 97.2–99.8% |

High ordering scores can reflect length, span presence or lexical markers. They
are **not response-quality scores** and do not select an optimal intervention
layer or strength. Confidence intervals are pair-level and do not model every
dependence between examples from the same document/context.

## Phase 3: promote and validate

```bash
uv run --locked python -m research.steering_experimentation.promote_lab_catalog
uv run --locked python -m website.api.check_setup
uv run --locked python -m research.steering_experimentation.verify_lab_catalog --device mps
```

Expected preflight: **9 artifacts, 341/341 vectors**. Promotion reuses existing
artifacts when absent from staging and refuses to overwrite existing versions
with different content. Extraction alone never updates the runtime catalog.
An intentional regeneration with changed content needs a new artifact release.

## Phase 4: serve and test the complete flow

```bash
uv run --locked python -m website.api.server
# In another terminal:
uv run --locked python -m research.steering_experimentation.verify_multifeature_api \
  --output /tmp/secondthought-feature-smoke.json
node website/frontend/tests/browser-smoke.mjs
```

The catalog supplies checkboxes, seven distinct web axes, independent layer and
pooling banks, exact artifact mappings, evidence and run metadata. Precise sliders
remain under **Layer controls**. Drag/keyboard release commits immediately;
inactive features retain settings without entering generation. Start at a zero
baseline and add one feature/layer before combining interventions.

Hook verification checks every vector's actual added delta and cleanup. The API
smoke checks each new feature with both poolings, all seven at shared/independent
layers, and baseline restoration. These verify integration. A claim of improved
writing still needs independent behavioral evaluation and human meaning review.
