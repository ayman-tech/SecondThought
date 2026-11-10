# Formality evals

Measures whether a rewrite reads as formal or professional. It adds columns next to the existing metrics; `evaluation.py` is unchanged.

- `src/secondthought/formality_evaluation.py`: the metrics
- `src/evaluation/evaluation_v2.py`: existing metrics plus formality (`evaluate_records_v2`, `format_evaluated_row_v2`, `summarize_v2`)
- `src/secondthought/add_formality.py`: adds the columns to an already-evaluated CSV

There are **no thresholds and no pass/fail**. These are raw values, to be calibrated later against human ratings.

## Columns

| Column | Kind | Meaning |
|---|---|---|
| `formality_original` | model | Mean sentence formality of the original (0 = informal, 1 = formal) |
| `formality_rewritten` | model | Mean sentence formality of the rewrite |
| `formality_gain` | calculation | `formality_rewritten − formality_original` |
| `formality_min_sentence` | model | Score of the least formal sentence in the rewrite |
| `formality_min_sentence_text` | evidence | That sentence |
| `formality_sentence_scores` | evidence | JSON list of `{"sentence", "score"}` for the rewrite |
| `register_marker_count` | rule | Number of informal markers left in the rewrite |
| `register_markers` | evidence | JSON list of `{"kind", "text"}` |

**Model:** [`s-nlp/roberta-base-formality-ranker`](https://huggingface.co/s-nlp/roberta-base-formality-ranker). It's loaded only when a scorer is passed.

**Sentences:** messages are split the way the product splits them before `both-t5`: each line, then `t5_rewriter.split_sentences`. Every sentence of every row is scored in one batched call.

**Register markers** (no model):
- `texting`: lowercase texting words (`u`, `gonna`, `lol`…), copied from `TEXTING` in `extension/triggers.js`.
- `all_caps`: words of 3+ capital letters. Known acronyms (`KNOWN_ACRONYMS`: the extension's list plus API, PDF, CEO…) and ticket IDs like `JIRA-123` are skipped.
- `exclamations` (`!!`+), `questions` (`??`+), `emoji`.
- `lowercase_i`: a standalone `i`, or `i'm`/`i'll`; `i.e.` doesn't count.

Standard contractions (`I'll`, `don't`) are not markers.

## Run it on an existing CSV

Writes a **new** file and refuses to overwrite one. Every input column keeps its value and position, and the formality columns go after the last metric column.

```bash
pip install -r requirements-formality.txt --extra-index-url https://download.pytorch.org/whl/cpu
PYTHONPATH=src python -m secondthought.add_formality outputs/both_detox_formalize.csv outputs/formality/both_detox_formalize_formality.csv
# markers only, no model download:
PYTHONPATH=src python -m secondthought.add_formality <in.csv> <out.csv> --no-model
# steering artifacts use other text columns:
PYTHONPATH=src python -m secondthought.add_formality steering_experimentation/artifacts/paradetox_activation_steering_evaluated.csv \
    outputs/formality/paradetox_activation_steering_evaluated_formality.csv --original-column toxic --rewritten-column generated
```

Tests: `PYTHONPATH=src pytest tests`. They use a fake scorer; the one real-model test is skipped if `transformers` isn't installed.

## Label-mapping check

- `config.id2label` is `{0: "informal", 1: "formal"}`. The scorer reads the "formal" index from the config instead of assuming it.
- Spot check (P(formal)):

| Sentence | P(formal) |
|---|---|
| "I would be grateful if you could send the report by Friday." | 0.9613 |
| "yo u gonna send that report or what lol" | 0.0052 |
| "Please replace it before merging." | 0.9969 |
| "This rollout is a complete shitshow." | 0.1504 |

## First result: `both-t5` on the 35 workplace messages

`outputs/formality/both_detox_formalize_formality.csv`:

| average_formality_original | average_formality_rewritten | average_formality_gain | average_formality_min_sentence | formality_gain_positive_rate | register_marker_free_rate |
|---|---|---|---|---|---|
| 0.5581 | 0.8004 | 0.2423 | 0.6897 | 0.9143 | 1.0 |

## Caveats

- **License:** CC BY-NC-SA 4.0 (non-commercial).
- **Needs calibration:** like Detoxify, it was trained outside the workplace domain (GYAFC and the Pavlick & Tetreault corpus), so its scores need calibrating against workplace ratings.
- **Possible bias toward our formalizer:** GYAFC is also what the `formalize` step was trained on, so the scorer may favour that model's style.
- **Formal is not polite:** "Do not dump your unfinished stuff on me…" scores 0.995 formal. Short, correct imperatives score low: "Roll it back before the demo." scores 0.28. Read these columns next to the toxicity columns, never instead of them.
- **Markers don't fire on this set:** the 35 messages contain no texting words, so the marker-free rate is 1.0 here. The markers matter more for casual inputs.
