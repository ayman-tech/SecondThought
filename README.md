# SecondThought

SecondThought is an MVP for testing whether an LLM can rewrite emotionally charged workplace messages professionally without losing criticism, urgency, facts, or requested actions.

The current system is an OpenAI baseline, not the final NLP model. Prompts, model configuration, datasets, generation, and evaluation are separate so each can be changed independently.

## Setup

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Set `OPENAI_API_KEY` in your shell or load it from `.env`:

```bash
set -a
source .env
set +a
```

Never commit `.env` or an API key.

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

Run the initial deterministic checks:

```bash
secondthought evaluate \
  --predictions outputs/baseline.csv \
  --output outputs/baseline_evaluated.csv
```

The baseline CSV keeps the original and rewritten messages side by side and records request latency and token usage. The evaluated CSV adds simple reproducible metrics: number recall, word overlap, edit ratio, length ratio, and exact match. Human review is still required to judge meaning, urgency, criticism, and usefulness. Model information and the UTC timestamp are always the last two CSV columns.

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
