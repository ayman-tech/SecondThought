# Model-agnostic activation steering

For the website's pinned Qwen catalog pipeline, use `extract_lab_vectors.py`
and `promote_lab_catalog.py`. Fluency now uses that same all-layer pipeline;
see [dataset preparation and reproduction](../../docs/FLUENCY_EXTRACTION.md).
The [expanded feature pipeline](../../docs/FEATURE_EXTRACTION.md) adds pinned
adapters for simplification, conciseness, empathy and politeness using the same
mean-difference extraction and catalog publication workflow.
The general research runner below produces separate experimental artifacts.

For configurable synthetic low/high pairs, use the
[synthetic experiment workbench](../../docs/SYNTHETIC_EXPERIMENTS.md). It plans
scenario splits, generates or imports teacher responses, prepares pairs, extracts
all layers, and publishes an isolated catalog for website testing.

Start the current feature-by-feature experiment with
[the empathy notebook](empathy_synthetic_steering.ipynb): a fixed empathy contrast,
50 fixed original messages, teacher-generated empathetic rewrites, pair review,
JSONL/CSV export, all-layer extraction, and an isolated website catalog. The source
is checked verbatim; these are parallel rewrites, not prompt/reply pairs. Exact
teacher prompts from the earlier three-pair pilot can be reused with provenance.
Set the teacher model and credentials before running its generation cell. It does
not generate paid teacher calls until the generation cell is run. The final cells
load Qwen to extract 48 vectors and print commands for the test website on port
8004, while preserving the normal serving catalog.

`run_experiment.py` learns a target-minus-source direction from any paired-text
dataset, ranks every decoder layer with mean and final-token pooling on a disjoint
holdout, saves a reusable artifact, and generates/analyzes outputs with the final
candidate.

GYAFC example (the restricted corpus stays outside the repository):

```bash
PYTHONPATH=src .venv/bin/python research/steering_experimentation/run_experiment.py \
  --model HuggingFaceTB/SmolLM2-135M \
  --dataset-loader gyafc \
  --dataset /path/to/GYAFC_Corpus \
  --feature formality \
  --extraction-pairs 8000 \
  --heldout-pairs 2000 \
  --artifact research/steering_experimentation/artifacts/smollm2_135m_gyafc_formality.pt \
  --candidate-report research/steering_experimentation/artifacts/smollm2_135m_gyafc_candidates.csv \
  --generation-input data/workplace_eval/input.jsonl \
  --generation-output research/steering_experimentation/artifacts/smollm2_135m_formality_outputs.csv \
  --summary-output research/steering_experimentation/artifacts/smollm2_135m_formality_summary.csv \
  --alphas 1 2
```

ParaDetox uses the same engine; only the adapter and paired columns change:

```bash
PYTHONPATH=src .venv/bin/python research/steering_experimentation/run_experiment.py \
  --model MODEL_ID \
  --dataset-loader huggingface \
  --dataset s-nlp/paradetox \
  --source-column en_toxic_comment \
  --target-column en_neutral_comment \
  --feature detoxification \
  --artifact research/steering_experimentation/artifacts/MODEL_paradetox.pt \
  --candidate-report research/steering_experimentation/artifacts/MODEL_paradetox_candidates.csv
```

CSV and JSONL pair files are supported with `--dataset-loader file`. Set
`--source-column`, `--target-column`, and optionally `--group-column`; no code
changes are required. Alpha multiplies the raw average target-minus-source delta,
matching the original Qwen formality experiment.

Use `--reuse-artifact` with the same arguments to regenerate or analyze another
sample without repeating direction extraction and candidate selection.
Add `--candidate layer16_final_token` to test a specific saved candidate instead
of the artifact's automatically selected candidate.
