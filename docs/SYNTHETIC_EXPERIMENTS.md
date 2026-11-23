# Synthetic steering experiments

Define a contrast, generate low/high versions of the same scenarios, and extract
directions using the existing mean-difference estimator. This workbench supports
new feature IDs as well as experimental replacements of existing features.
Mean pooling and final-token pooling remain the two extraction options.

Run commands from the repository root after the normal Python setup in
[LOCAL_TESTING.md](LOCAL_TESTING.md). Generation uses the existing `openai` dependency.

## 1. Define and plan an experiment (offline)

Copy `research/steering_experimentation/synthetic_examples/formality.json` and
edit the feature ID, version, label, low/high descriptions, preservation rules,
and nuisance controls. Start with a narrow contrast. `scale` explicitly selects
`raw` or `unit_l2` inference vectors; alpha values across scales are not equivalent.

Supply JSONL scenarios with `id`, `family`, `task`, `context`, and optional
`required_terms`. Include at least 10 independent families. Keep variants of the
same situation in the same family. Names, numeric facts, requested actions, and
the speaker's stance should stay constant across a pair.

```sh
RUN=data/synthetic/formality-synthetic-v1
.venv/bin/python -m research.steering_experimentation.synthetic_pipeline plan \
  --definition research/steering_experimentation/synthetic_examples/formality.json \
  --scenarios research/steering_experimentation/synthetic_examples/scenarios.jsonl \
  --run "$RUN" --seed 42 --variants 1
```

Inspect `feature.json`, `requests.jsonl`, and `plan.json` before generation.
The supplied 20 scenarios are a small plumbing pilot, not a sufficient quality
benchmark. Expand their variety before drawing conclusions.

Families are assigned approximately 60% extraction, 20% held-out ordering, and
20% reserved evaluation **before generation**. A run's plan is immutable and
fingerprinted. Change the feature or teacher settings by creating a new run.

## 2. Generate or import pairs

For a hosted teacher, set `OPENAI_API_KEY` in your environment and explicitly
choose its model ID. This command makes external API calls and may incur charges:

```sh
.venv/bin/python -m research.steering_experimentation.synthetic_pipeline generate \
  --run "$RUN" --provider responses --model YOUR_TEACHER_MODEL \
  --max-requests 20 --max-output-tokens 512
```

An OpenAI-compatible local server can use `--provider chat --model MODEL_ID
--base-url http://127.0.0.1:PORT/v1` instead. No teacher is selected automatically.
No extraction model is used as a teacher automatically.

`--max-requests` bounds calls for that invocation. Re-running resumes unrecorded
requests; already recorded failures are also skipped. There are no automatic SDK
retries. Errors are recorded without API keys or provider error bodies. For failed
requests, inspect the cause and use a separate response import or a new run.

Alternatively, generate elsewhere using the exported prompts and import JSONL:

```json
{"request_id":"COPY_FROM_REQUESTS","experiment_id":"COPY_FROM_PLAN","output":{"low":"Lower-feature text.","high":"Higher-feature text."},"teacher":{"provider":"external","model":"YOUR_MODEL"}}
```

Preserve the IDs exactly. Keep one response per request. Raw responses, usage,
requested/returned model IDs, prompts, and experiment data stay under ignored
`data/synthetic/`; credentials are never written by the workbench.

## 3. Prepare and review

```sh
.venv/bin/python -m research.steering_experimentation.synthetic_pipeline prepare \
  --run "$RUN"
```

Use `--responses PATH` for an imported JSONL. Preparation rejects identical or
duplicate endpoints, wrong numeric facts, missing required terms, excessive
length differences, invalid JSON, and responses from another experiment.
Inspect `dataset/accepted.jsonl`, `rejected.jsonl`, and `summary.json`.

These checks do not establish semantic equivalence or a clean feature contrast.
For manual review, create a JSON list of accepted request IDs and supply
`--approvals PATH --output "$RUN/reviewed"`. Supply that reviewed dataset to
extraction using `--dataset "$RUN/reviewed/pairs.jsonl"`.

The extractor's `pairs.jsonl` excludes the reserved `evaluation.jsonl` split.
Preparation needs at least two accepted extraction and held-out pairs to run;
this is a technical minimum, not evidence of a reliable direction. Existing
prepared datasets cannot be overwritten.

## 4. Extract every layer

```sh
.venv/bin/python -m research.steering_experimentation.synthetic_pipeline extract \
  --run "$RUN" --device mps --batch-size 8 --max-length 256
```

Use `cpu` or `cuda` as appropriate. The pinned Qwen model is loaded through the
common extractor and Hugging Face cache. This produces 48 directions: both
pooling methods for all 24 decoder blocks. Each is the average high-minus-low
activation difference. Held-out pair ordering is measured separately for each
direction. Provenance carries the definition, data hashes, teacher metadata,
split policy, extraction settings, and review status. Existing artifacts cannot
be overwritten.

## 5. Open an isolated website experiment

```sh
.venv/bin/python -m research.steering_experimentation.synthetic_pipeline publish \
  --run "$RUN"
export SECONDTHOUGHT_LAB_CATALOG="$PWD/$RUN/serving/catalog/qwen2_5_0_5b.json"
export SECONDTHOUGHT_LAB_ARTIFACT_ROOT="$PWD/$RUN/serving"
.venv/bin/python -m website.api.check_setup
.venv/bin/python -m uvicorn website.api.server:app --host 127.0.0.1 --port 8004
```

Visit `http://127.0.0.1:8004/steering`. The publisher copies the base catalog and
retained artifacts into the experiment directory. It replaces an existing
feature's selectable experimental vector family, or adds a new feature, with
all 48 vectors. Existing features and legacy references remain available. The
repository's serving catalog and artifacts are not modified.

The website discovers the feature, pooling options, layer vectors, and layer
colours from that catalog. Colours represent held-out pair ordering, not output
quality. Restart the server when switching catalogs. Unset both environment
variables to return to the normal catalog.

## 6. Test whether control was established

Use reserved scenarios and fresh tasks. Compare alpha 0 with positive and negative
alpha at the same layer, prompt, and decoding settings; then test layer mixtures.
Record feature movement, meaning preservation, repetition, and task completion.
Compare with the original catalog in a separate server. Successful extraction or
high pair-ordering accuracy alone does not establish useful generation control.

The current workbench exports reserved evaluation pairs; it does not automatically
score generated responses or promote an experiment into the production catalog.
