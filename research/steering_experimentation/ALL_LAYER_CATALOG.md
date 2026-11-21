# Qwen all-layer catalog: extraction, promotion, and verification

This release covers `Qwen/Qwen2.5-0.5B-Instruct` at pinned revision
`7ae557604adf67be50417f59c2c2f167def9a775`. It contains **144 directions**:
24 decoder block outputs × two extraction pooling methods × three features.
Five unchanged legacy entries preserve the existing website defaults.
Fluency adds 48 vectors using the existing mean-difference algorithm. See its
[preparation and reproduction guide](../../docs/FLUENCY_EXTRACTION.md).

## Extraction profile

- Capture each actual decoder block output through forward hooks, before the
  model-level final normalization. Embeddings and final normalized outputs are
  not substituted for decoder blocks. This includes the final decoder index 23.
- Mean pooling ignores padding; final-token pooling selects the last non-padding
  position. Both describe extraction. Inference adds the direction at every token.
- Compute target-minus-source paired differences with raw-text tokenization, no
  chat template. Store raw float32 vectors; formality defaults use raw scale and
  detoxification defaults use unit-L2 scale.
- Extract with model float32 on MPS, batch size **16 pairs / 32 sequences**, maximum
  128 tokens per sequence, seed 42. Sum float32 batch deltas into float64 totals.
  Record truncated-sequence counts rather than hiding truncation.
- GYAFC: local aligned training files, normalized-source deduplication across
  domains; 4,000 extraction and 1,000 held-out sources per domain. This new split
  deliberately prevents duplicate-source leakage and is not a numerical
  reproduction of the old notebook's row-based split. Existing vectors are kept.
- ParaDetox: reuse the notebook's existing `paradetox_direction_pairs.csv`
  extraction/held-out split unchanged (8,000/2,000). Assert unique, disjoint sources
  and nonempty, non-copy pairs before loading the model.
- Fluency: filtered IteraTeR-HUMAN official train/development pairs, with document
  and sentence isolation. 542 extraction / 84 held-out pairs; batch size 8 and
  maximum 256 tokens, with no truncation in the recorded run. Runtime scale is
  unit-L2; the preparation guide documents the remaining dataset limitations.

Each feature artifact stores the 48 raw vectors, candidate measurements, dataset
file and split hashes, pinned model/tokenizer revisions, activation boundary,
precision, environment, and extraction/capture source-code hashes. No GYAFC source
sentences or model weights are copied into the artifacts or public frontend.

## What the measurements establish

Formality/detoxification directions use 2,000 held-out pairs; fluency uses 84.
All use projection ordering:
the proportion whose target-minus-source activation difference projects positively
onto the learned direction. This measures held-out feature separation, not
generation quality, semantic preservation, or a recommended alpha range.

| Feature | New vectors | Held-out ordering range |
| --- | --- | --- |
| Formality | 48 | 0.4990–0.9595 |
| Detoxification | 48 | 0.8600–0.9965 |
| Fluency | 48 | 0.5833–0.8095 |

The weakest formality entry is near chance. It remains explicitly experimental
for a lab, not labeled an effective or optimal intervention. Scales differ across
layers and features; the existing -2 to +2 interaction range is an operator limit,
not a calibrated guarantee. No shuffled-control study or full rewrite-quality
benchmark is claimed for this extraction release.

The original `artifacts/lab_v1/generation_smoke.json` records real MPS/float32 execution of all
101 catalog entries at strength +0.5 using short generation probes. For each entry,
an observer checks that the exact expected shift was added at the declared block
and that all hooks were removed. The report also confirms that the original
layer-11 default produces identical text through the compatibility and original
mixed-steering contexts on the same loaded model. Short probe samples are retained
for inspection; they are not evidence that each direction improves rewriting.
The current verifier also covers fluency (149 entries total); rerun it to obtain
a report for the current catalog version.

## Reproduce offline

From the repository root, with the pinned model snapshot already cached and the
licensed GYAFC corpus available locally:

```bash
uv run python -m research.steering_experimentation.extract_lab_vectors \
  --gyafc /path/to/GYAFC_Corpus --device mps --batch-size 16

uv run python -m research.steering_experimentation.prepare_fluency_pairs --download
uv run python -m research.steering_experimentation.extract_lab_vectors \
  --feature fluency --device mps --batch-size 8 --max-length 256

uv run python -m research.steering_experimentation.promote_lab_catalog

uv run python -m research.steering_experimentation.verify_lab_catalog --device mps
```

CPU may be selected explicitly for another environment; its outputs require their
own provenance and checks. CUDA inference is not validated by this MPS run.

Extraction writes to `research/steering_experimentation/artifacts/lab_v1/`:

- One `.pt` artifact and one readable `.json` candidate/provenance report per feature.
- `generation_smoke.json` from the real-model verifier.
- `coverage_summary.json`, a summary of the promoted release measurements.

Promotion checks complete layer/pooling coverage, sample counts, model/site
metadata, tensor integrity, and legacy references. Runtime files are copied via
temporary paths and the catalog manifest is published last. Existing versioned
runtime artifacts with different bytes are never overwritten. A future extraction
release must use new artifact identifiers/filenames and a new manifest version;
rerunning extraction alone does not change serving assets.

## Serving and extension points

The read-only endpoint is `GET /api/v2/lab/catalog`. The existing v1 config and
layer validation now project their default choices from the checked catalog,
exposing every index 0–23. Invalid catalog vectors are unavailable, not synthesized.
The catalog digest participates in the runtime steering/cache version.

The catalog also exposes `layer_evidence_profiles` for the website's layer
heatmap: exact compatibility defaults plus six separate feature/pooling
cohorts from this release. Colours use held-out pair ordering with Wilson 95%
intervals and sample counts. Missing legacy scores are left unmeasured, never
filled from a newer extraction. These measurements describe activation feature
separation, not causal rewrite quality or semantic preservation. The UI uses only the six new-extraction cohorts and joins colours to the exact
vector IDs sent to generation; there is no separate colour-view selector.

Older v1 API clients retain compatibility defaults: legacy directions at 0, 4,
11, 21 and 22, and new mean-pooled formality at other indices. The lab UI now
keeps an independent layer/pooling/strength bank for each enabled feature and
sends a v2 intervention list, preserving multiple features at a shared layer. Reset uses Formality/mean and layer 11 at
+0.5. All 144 feature/layer/pooling choices have saved held-out scores. The full
matrix is available through the catalog and `compile_interventions`/
`steering_context`. Exact vector choices are validated, echoed in run events and
included in cache keys. Task presets, custom instructions and bounded input/output budgets are live
through v1. Additional model adapters and live response evaluation graphs
remain subsequent phases of the backend design.

`secondthought.lab.interventions` resolves typed vector IDs, validates strengths
and model compatibility, supports several directions at one layer, and owns a
cleanup-safe hook context. It does not bypass the serving worker's generation
lock; callers must preserve model-instance isolation.

Restart the website process after catalog or backend changes. A process caches
its verified catalog; publishing files cannot mutate an in-flight model session.
Run `make website-test` for catalog/extraction/API/unit checks and the optional
browser smoke script against the restarted server for real generation checks.
