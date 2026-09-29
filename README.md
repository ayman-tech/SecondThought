# SecondThought

SecondThought explores rewriting emotionally charged messages into respectful, professional language while preserving meaning, criticism, urgency, facts, and requested actions. It includes local T5 inference and fine-tuning notebooks, plus an OpenAI baseline with a CLI, Gradio interface, and evaluation tools.

## Setup

Use Python 3.12 (the project supports Python 3.12–3.13). Install the application, local inference, notebook, and development dependencies:

```bash
uv sync
source .venv/bin/activate
```

Alternatively, on macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. Local notebook inference uses the CPU and does not require an NVIDIA GPU or an API key. The training notebook keeps its own Colab dependency installation cell.

Only the OpenAI baseline needs an API key. Set `OPENAI_API_KEY` in your shell, or prepare and load a local `.env` file:

```bash
cp .env.example .env
# Edit .env to set OPENAI_API_KEY, then:
set -a
source .env
set +a
```

Never commit `.env` or an API key.

## Try the saved model

Open [notebooks/inference.ipynb](notebooks/inference.ipynb) in VS Code and choose **Select Kernel → Python Environments → .venv/bin/python**. Run the cells in order, then type a sentence when the last cell prompts you. Rerun that cell for each new sentence; no retraining is needed.

Set `MODEL_DIR` to your extracted model folder, using an absolute path if necessary (relative paths are resolved from the notebook kernel’s working directory). The notebook can also extract a matching ZIP whose top-level folder has the same name. Inference uses the local CPU and local model files; no NVIDIA GPU is required. Review outputs for neutral tone and preservation of meaning.

`pyproject.toml` and `uv.lock` manage local dependencies. The training notebook keeps its separate Colab installation cell.

## Fine-tune T5-small

Open [notebooks/train.ipynb](notebooks/train.ipynb) in [Google Colab](https://colab.research.google.com/) using **File → Upload notebook**, or Colab's GitHub tab. Select **Runtime → Change runtime type → GPU** and run the cells in order. Use a fresh Python 3.10+ runtime; the first cell installs pinned dependencies alongside Colab's existing PyTorch.

The notebook fine-tunes `google-t5/t5-small` on [ParaDetox](https://huggingface.co/datasets/s-nlp/paradetox), mapping toxic comments to neutral rewrites. It explains data preparation, tokenization, training, evaluation, and inference. Repeated toxic inputs stay in the same split to prevent leakage.

- Start with `SMOKE_TEST = True` in the configuration cell to check five training steps, evaluation, saving, reloading, and generation on a small subset.
- For full training, set `SMOKE_TEST = False` and rerun from the configuration cell onward. Current settings are 5 epochs, learning rate `3e-4`, batch size 8, and gradient accumulation 2, using full precision.
- If GPU memory is insufficient, lower `BATCH_SIZE` to 4 or 2. Training time depends on the assigned GPU. CPU execution is supported but much slower.
- The best checkpoint is selected by validation loss. Test loss and input/reference/output examples are shown afterward; loss alone does not establish toxicity reduction or meaning preservation.

The final model and tokenizer are exported to `./epoch5`; the last cell downloads a ZIP. Smoke runs use separate folders ending in `-smoke` and `-smoke-checkpoints`. Download your model before the Colab session ends. Training checkpoints live separately in `./epoch5-checkpoints`.

The notebook includes a reusable `detoxify(text)` function and instructions for loading the exported model later. Training runs locally within your Colab runtime; the notebook does not publish the model to Hugging Face or enable external experiment tracking.

## Run the MVP

Rewrite one message:

```bash
secondthought rewrite "This implementation is careless. Fix the timeout before merging."
```

Launch the minimal web interface:

```bash
secondthought-app
```

Generate baseline predictions for the sample dataset:

```bash
secondthought batch \
  --dataset data/workplace_eval/sample.jsonl \
  --output outputs/baseline.csv
```

Run the deterministic metrics, including typed critical-value preservation:

```bash
secondthought evaluate \
  --predictions outputs/baseline.csv \
  --output outputs/baseline_evaluated.csv
```

To include the two optional learned evaluators, install their dependencies and add
the flag:

```bash
uv sync --extra evaluation

secondthought evaluate \
  --predictions outputs/baseline.csv \
  --output outputs/baseline_evaluated.csv \
  --with-learned-metrics
```

The learned metrics use Detoxify's `original` toxicity classifier and
`sentence-transformers/all-mpnet-base-v2` by default. The first run downloads the
model weights; later runs use the local cache. `--toxicity-model`,
`--similarity-model`, and `--device` can override these defaults.

The evaluated CSV contains input/output toxicity, absolute and relative toxicity
reduction, semantic cosine similarity, and critical-value counts and details. The
critical-value implementation normalizes numbers and number words, dates, times,
money, percentages, measurements, URLs, email addresses, mentions, ticket IDs,
and technical identifiers. Missing and newly introduced values are serialized as
JSON columns. If a prediction CSV has a `critical_values` column, it must be a JSON
list and is used as the source-of-truth preservation list; this is the recommended
way to cover names, projects, or other literal values that deterministic extraction
cannot identify safely. Semantic similarity remains the proxy for broader intent
and requested-action preservation.

Detoxify and Sentence-Transformers are separate learned models, not ground truth.
The toxicity classifier is trained on internet-comment data and can be biased or
miscalibrated for workplace language. High embedding similarity can miss changed
negation, urgency, deadlines, or requested actions. Always inspect the individual
preservation columns and calibrate learned-score thresholds on human-labeled
development records. Neither learned score is currently converted to a pass/fail
decision by the CLI.

The CSV retains the original and rewritten messages, request latency, and token
usage. Model information and the UTC timestamp remain the last two columns.

## Change the experiment

- Model and generation settings: `config/default.toml`
- Baseline instructions: `prompts/constrained.txt`
- Evaluation inputs: `data/workplace_eval/*.jsonl`
- Provider implementation: `src/secondthought/rewriter.py`
- Metrics: `src/secondthought/evaluation.py`

Environment variables override the main settings:

```bash
export SECONDTHOUGHT_MODEL="another-model-id"
export SECONDTHOUGHT_PROMPT="prompts/another-prompt.txt"
```

## Repository layout

```text
config/                 Runtime configuration
data/workplace_eval/    Versioned evaluation inputs
prompts/                Versioned model instructions
src/secondthought/      Application and evaluation code
tests/                  Offline unit tests
outputs/                Generated artifacts (ignored by Git)
reports/                Course reports
```

## Test

Tests do not call the OpenAI API.

```bash
pytest
```
