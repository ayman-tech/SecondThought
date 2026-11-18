# Runtime artifacts

Files the **product code loads at runtime**. Nothing here is an experiment output;
those live in `research/`.

| File | Loaded by | Made by |
| --- | --- | --- |
| `qwen2_5_0_5b_gyafc_formality_directions.pt` | `src/secondthought/steering_rewriter.py` | `research/steering_experimentation/activation_steering.ipynb` |
| `qwen2_5_0_5b_paradetox_directions.pt` | `src/secondthought/steering_rewriter.py` | `research/steering_experimentation/paradetox_hidden_states.ipynb` |
| `qwen2_5_0_5b_formality_all_layers_v1.pt` | Checked lab catalog | `research/steering_experimentation/extract_lab_vectors.py` |
| `qwen2_5_0_5b_detoxification_all_layers_v1.pt` | Checked lab catalog | Same extraction profile, saved ParaDetox split |
| `catalog/qwen2_5_0_5b.json` | `secondthought.lab.catalog` | `research/steering_experimentation/promote_lab_catalog.py` |

The catalog adds 96 experimental directions: 24 decoder blocks × mean/final-token
pooling × formality/detoxification. The five pre-existing runtime references remain
separate entries, making 101 vectors total. Their files/checksums are unchanged.
The website's compatibility defaults retain the five existing choices; newly
available indices use the new mean-pooled formality direction. Independent feature/
pooling selection remains a subsequent runtime/UI integration phase.

Catalog entries specify a pinned model revision, exact block-output boundary,
vector checksum, pooling, raw norm, scaling, strengths, and behavioral status.
Legacy extraction revisions/precision remain explicitly unknown. Checksums, tensor
shape, finite/nonzero contents, candidate metadata, and model compatibility are
validated before availability. A broken new artifact disables its vectors while
leaving valid references inspectable; a broken required legacy asset prevents
model readiness. Model weights are not included in this catalog.

See [all-layer extraction and verification](../research/steering_experimentation/ALL_LAYER_CATALOG.md)
for reproduction commands, held-out measurements, and the limitations of those checks.

## Promoting a new version

The research notebooks write to `research/steering_experimentation/artifacts/`. These
files are **copies**, so re-running a notebook does not change what the product uses
until you promote the result on purpose:

```bash
cp research/steering_experimentation/artifacts/<file>.pt artifacts/
```

Then check that `steering_rewriter.py` still loads it, and commit both together.

Large model weights do not belong here; they go in `models/`, which is git-ignored.
