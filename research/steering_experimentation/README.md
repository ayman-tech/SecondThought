# Model-agnostic activation steering

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
