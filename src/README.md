# SecondThought Source and Evaluation Guide

This directory contains the Python implementation of SecondThought. The current
evaluation pipeline is in `secondthought/evaluation.py`, and the `evaluate` CLI
command is wired in `secondthought/cli.py`.

The project evaluates saved model outputs rather than evaluating requests in real
time. A predictions CSV must contain at least:

```text
original_text, rewritten_text
```

The evaluator currently focuses on three complementary questions:

1. Did the rewrite reduce toxicity?
2. Did the rewrite preserve the overall meaning and intent?
3. Did it preserve concrete facts and values that must not change?

No single metric answers all three questions. A copied toxic input can have very
high semantic similarity, while a polite but unrelated output can have very low
toxicity. The metrics must therefore be interpreted together.

## Running the evaluation

Install the optional learned evaluators:

```bash
uv sync --extra evaluation
```

Then evaluate a saved predictions file:

```bash
secondthought evaluate \
  --predictions outputs/constrained.csv \
  --output outputs/constrained_evaluated.csv \
  --with-learned-metrics
```

The first learned-metric run downloads the external model checkpoints and caches
them locally. Future runs reuse the cached files. The evaluation records are
processed in batches; the evaluator models are loaded only once per command.

Running without `--with-learned-metrics` computes critical-value preservation and
the deterministic diagnostic metrics, but omits toxicity and semantic similarity:

```bash
secondthought evaluate \
  --predictions outputs/constrained.csv \
  --output outputs/constrained_evaluated.csv
```

## Metrics added in the current evaluation setup

### 1. Toxicity and toxicity reduction

The default toxicity evaluator is:

```python
Detoxify("original")
```

Source:

- [UnitaryAI Detoxify repository](https://github.com/unitaryai/detoxify)
- [Detoxify checkpoint-loading implementation](https://github.com/unitaryai/detoxify/blob/master/detoxify/detoxify.py)

The `original` model is a pretrained, BERT-based toxic-comment classifier trained
for the original Jigsaw Toxic Comment Classification task. SecondThought uses only
its `toxicity` output. It scores both the original and rewritten text so that we
can measure the final toxicity and the change caused by rewriting.

The model can be changed with:

```bash
--toxicity-model MODEL_TYPE
```

#### Limitation

Detoxify is a separate learned evaluator, not ground truth. It was developed for
internet-comment toxicity rather than workplace communication. It may:

- over-score profanity used in a quotation or non-hostile context;
- behave differently around identity terms;
- miss condescension, sarcasm, blame, or aggressive workplace language that does
  not contain commonly toxic wording;
- assign different scores to text variations that a human considers equivalent.

The scores should be calibrated against human-labeled workplace examples before
choosing a toxic/non-toxic threshold. The implementation deliberately reports raw
scores and reductions without declaring a universal pass threshold.

### 2. Semantic similarity

The default semantic evaluator is:

```text
sentence-transformers/all-mpnet-base-v2
```

Source:

- [all-mpnet-base-v2 model card](https://huggingface.co/sentence-transformers/all-mpnet-base-v2)
- [Sentence-Transformers documentation](https://sbert.net/docs/sentence_transformer/pretrained_models.html)

The model converts the original and rewritten messages into normalized sentence
embeddings. The evaluator calculates their cosine similarity. Higher similarity
usually indicates that the two sentences discuss similar content.

The model can be changed with:

```bash
--similarity-model MODEL_ID
```

#### Limitation

This is also a learned evaluator. Cosine similarity is useful as an intent
preservation proxy, but it does not prove that intent was preserved. For example:

```text
Submit the report today.
Submit the report whenever convenient.
```

These sentences may have high similarity despite having different urgency. An
embedding score can also miss changed negation, responsibility, requested action,
deadline, or criticism. Copying the original input produces almost perfect
similarity even when the input remains toxic. Semantic similarity must therefore
be read alongside toxicity and critical-value preservation.

### 3. Critical-value preservation

Critical-value preservation is implemented locally and does not call an external
model. Its purpose is to detect factual details that embedding similarity can
miss.

For example:

```text
Original:  Send all 12 files by 5 PM.
Rewrite:   Please send the files tomorrow.
```

The sentences remain semantically related, but the rewrite removed `12` and
changed the deadline. For a workplace writing assistant, this is a serious failure
even if the output is fluent and non-toxic.

The extractor currently recognizes and normalizes:

- numeric values and number words;
- counts and quantities;
- dates, weekdays, relative dates, and times;
- money and percentages;
- durations, data sizes, physical units, and similar measurements;
- email addresses, URLs, and `@mentions`;
- ticket IDs such as `INC-42`;
- uppercase acronyms and common code-style identifiers.

Normalization allows safe formatting changes to match. Examples include:

```text
2 files       <-> two files
5 PM          <-> 5 p.m.
$1,000        <-> $1000
12%           <-> 12 percent
March 2nd     <-> March 2
```

Matches are type-aware and duplicate-aware. If the original contains the same
value twice but the output contains it once, only one occurrence is counted as
preserved. The evaluator also reports structured values that appear in the output
but not in the input. This helps expose changed or invented deadlines, quantities,
IDs, and other details.

Count nouns receive slightly looser handling because a valid rewrite may change
`20 times` into `20 API calls`. The quantity remains critical, while the exact
noun may be a legitimate paraphrase. Physical units, currencies, percentages,
dates, and identifiers remain type-sensitive.

#### Human-authored critical values

Regex extraction cannot safely infer every person name, client name, project name,
or domain-specific identifier. Evaluation datasets can therefore provide a
`critical_values` column containing a JSON list:

```json
[
  {"type": "project", "value": "Project Atlas"},
  {"type": "client", "value": "Acme Corp"},
  {"type": "deadline", "value": "5 PM", "normalized": "17:00"}
]
```

A simple string list is also accepted:

```json
["Project Atlas", "Acme Corp"]
```

When annotations are provided, they define the values used for preservation
recall. Automatic extraction is still used to identify unsupported values added
to the output. Batch generation carries a dataset's `critical_values` field into
the predictions CSV.

Annotations are recommended for the frozen product benchmark. Automatic
extraction is useful for broad diagnostics, but annotations make the evaluation
requirements explicit and auditable.

#### Limitation

Critical-value preservation does not establish that the relationship between
values was preserved. A rewrite could retain `Alice`, `Bob`, and `5 PM` while
changing who must send something to whom. It also cannot reliably determine
whether a requested action was paraphrased correctly. Semantic comparison and
human review remain necessary for those cases.

## Evaluated CSV columns

An evaluated CSV retains the input prediction columns and appends metric columns.
When learned metrics are enabled, the current output contains the following.

### Record and generation columns

| Column | Meaning |
|---|---|
| `id` | Stable identifier for the evaluation example. |
| `original_text` | Source message supplied to the rewriting system. |
| `rewritten_text` | Generated rewrite being evaluated. |
| `latency_ms` | Time taken to generate the rewrite, in milliseconds. This does not include the later offline evaluation. |
| `input_tokens` | Input-token usage reported by the generation provider, when available. |
| `output_tokens` | Output-token usage reported by the generation provider, when available. |
| `critical_values` | Optional JSON annotations carried from the evaluation dataset. This column appears only when supplied. |

### Critical-value columns

| Column | Meaning |
|---|---|
| `critical_value_count` | Number of required values found automatically or supplied through annotations. |
| `critical_value_preserved_count` | Number of required occurrences found in the rewrite after normalization. |
| `critical_value_recall` | `preserved_count / critical_value_count`. It is `1.0` when no critical values exist because there was nothing to lose. |
| `critical_value_missing_count` | Number of required value occurrences absent from the rewrite. |
| `critical_value_unsupported_count` | Number of automatically detectable structured values in the rewrite that were not present in the original. These may be inventions or changed values. |
| `critical_value_exact` | `True` only when no required value is missing and no unsupported structured value was added. |
| `critical_value_missing` | JSON array describing every missing value, including its type, raw source text, normalized form, and source offsets when automatically extracted. |
| `critical_value_unsupported` | JSON array describing every structured value found only in the rewrite. |

For a changed value such as `March 2` becoming `March 3`, expect both one missing
value and one unsupported value. That representation captures both sides of the
change.

### Toxicity columns

| Column | Meaning |
|---|---|
| `toxicity_original` | Detoxify toxicity score for the original text. Larger values indicate that the external classifier considers the text more toxic. |
| `toxicity_rewritten` | Detoxify toxicity score for the generated rewrite. |
| `toxicity_reduction` | `toxicity_original - toxicity_rewritten`. Positive is a reduction; zero is no change; negative means the rewrite scored as more toxic. |
| `toxicity_relative_reduction` | Toxicity reduction divided by the original score. This contextualizes the change but can be unstable when original toxicity is extremely close to zero. |

These values are classifier scores, not human probabilities or guarantees of
professionalism. A threshold must be selected on labeled development data before
reporting a binary detoxification success rate.

### Semantic-similarity column

| Column | Meaning |
|---|---|
| `semantic_similarity` | Cosine similarity between normalized all-mpnet-base-v2 embeddings of the original and rewrite. Higher means more similar according to the external encoder. No universal intent-preservation threshold is assumed. |

### Existing diagnostic columns

These metrics predate the three core evaluators and remain useful for diagnosing
model behavior. They are not sufficient product-quality metrics by themselves.

| Column | Meaning |
|---|---|
| `number_recall` | Legacy recall of digit-based numeric surface values. Unlike critical-value recall, it does not understand the value's type or unit. |
| `word_overlap` | Jaccard overlap between the unique lowercased word sets in the original and rewrite. |
| `edit_ratio` | Character-level change ratio derived from `SequenceMatcher`; `0` means identical and larger values mean more editing. |
| `length_ratio` | Rewrite character length divided by original character length. Values below `1` indicate shortening and values above `1` indicate expansion. |
| `exact_match` | Whether the original and rewrite are identical after trimming leading and trailing whitespace. |

### Reproducibility columns

| Column | Meaning |
|---|---|
| `model_info` | Identifier of the generation model, not the evaluator model. |
| `timestamp_utc` | UTC timestamp recorded when generation completed. |

`model_info` and `timestamp_utc` are deliberately retained as the final two CSV
columns. Provider `response_id` values are deliberately removed from evaluated
CSVs. The full order is: record text, semantic similarity, toxicity metrics,
critical-value metrics, legacy metrics, other generation metadata, `model_info`,
and `timestamp_utc`.

## Printed summary

After writing the evaluated CSV, the command prints dataset-level aggregates:

- number of examples;
- average legacy number recall, word overlap, edit ratio, and length ratio;
- exact-copy rate;
- micro critical-value recall;
- critical-value exact-success rate;
- total missing and unsupported critical values;
- average input toxicity, output toxicity, absolute reduction, and relative
  reduction when learned metrics are enabled;
- average semantic similarity when learned metrics are enabled;
- average generation latency when the input CSV contains `latency_ms`.

The CSV remains the authoritative artifact because it preserves every example and
makes failure analysis possible. Aggregate averages should never replace review
of missing values, unsupported values, low-similarity cases, or outputs whose
toxicity increased.

## Interpretation checklist

When comparing two rewriting checkpoints, ask:

1. Did `toxicity_rewritten` decrease without a drop in semantic similarity?
2. Did critical-value recall remain high, ideally with no changed deadlines, IDs,
   quantities, or monetary values?
3. Are there examples with high similarity but failed critical-value checks?
4. Are copied outputs inflating similarity while leaving toxicity unchanged?
5. Are large toxicity reductions caused by deleting important content?
6. Do the same patterns hold across workplace scenarios rather than only in the
   overall average?

The intended outcome is not the lowest possible toxicity score. It is a less
hostile message that still communicates the same facts, intent, urgency, and
requested action.
