# SmolLM2-135M GYAFC formality-steering report

## Protocol

- Model: `HuggingFaceTB/SmolLM2-135M` (base model, not the Instruct variant)
- Feature direction: GYAFC `formal - informal`
- Direction extraction: 8,000 non-copy training pairs, balanced across the two GYAFC domains
- Candidate selection: a disjoint, domain-balanced 2,000-pair holdout
- Candidates: all 30 decoder layers, with mean and final-token pooling (60 total)
- Candidate ranking: held-out paired ordering accuracy, then paired projection effect size
- Final generation set: 35 workplace records, greedy decoding, final candidate only
- Steering strengths: alpha 1 and alpha 2 only
- Alpha semantics: raw average target-minus-source displacement, matching the Qwen experiment

## Candidate selection

| Rank | Candidate | Held-out ordering accuracy | Effect size |
|---:|---|---:|---:|
| 1 | `layer10_mean` | 0.9415 | 1.2495 |
| 2 | `layer28_final_token` | 0.9310 | 1.1519 |
| 3 | `layer26_final_token` | 0.9280 | 1.1071 |
| 4 | `layer27_final_token` | 0.9275 | 1.1353 |
| 5 | `layer25_final_token` | 0.9210 | 1.0698 |

The final candidate is `layer10_mean`. Its raw direction norm is 8.0616. The
strong held-out ordering result establishes that it encodes a reproducible
formal-versus-informal distinction on GYAFC. It does not by itself establish
that intervening on this direction will produce faithful workplace rewrites.

## Generation diagnostics

| Metric | alpha 1 | alpha 2 |
|---|---:|---:|
| Records | 35 | 35 |
| Exact-copy rate | 0.5143 | 0.4000 |
| Mean word-set overlap | 0.8555 | 0.8025 |
| Mean edit ratio | 0.1046 | 0.1441 |
| Mean word-length ratio | 0.8798 | 0.8279 |
| Mean contraction count | 0.4571 | 0.4571 |
| Mean number recall | 0.9714 | 0.9381 |
| Mean critical-value recall | 0.9857 | 0.9524 |
| Critical-value exact rate | 0.9714 | 0.9143 |
| Missing critical values | 1 | 4 |
| Invented critical values | 0 | 0 |

Alpha 2 causes more rewriting than alpha 1, but the intervention is not a useful
monotonic formality control on this sample. Thirty of the 35 records produce the
same first rewrite at both strengths, contraction counts do not improve, and
many hostile terms remain unchanged. This is expected to some extent because
GYAFC supplies a formality direction, not a detoxification direction.

Content preservation degrades at alpha 2. It drops room 204 and 3 PM from
`input_002`, drops 92 Cedar Court from `input_004`, and both strengths omit the
canceled order 8427 from `input_018`. The deterministic critical-value metric
does not capture relational reversals: both strengths reverse the requested ice
amounts in `input_017` (200 g versus 2 kg) while retaining both literal values.
There are also action losses and meaning changes, such as deleting requested
follow-up clauses and reversing the intent of `input_034`.

## Conclusion

SmolLM2-135M contains a geometrically strong GYAFC formality direction at layer
10, but the base 135M model does not turn that direction into reliable,
meaning-preserving workplace formalization under this protocol. Alpha 1 is the
less damaging of the two requested strengths; alpha 2 increases editing while
lowering preservation. Neither should be treated as production-ready. A later
detoxification experiment should learn a separate `neutral - toxic` direction
from ParaDetox via the same dataset adapter rather than interpreting this GYAFC
direction as detoxification.

The metrics here are deterministic diagnostics. An independent formality
classifier or human ratings and a semantic model should be added before making
comparative claims about absolute formality quality.
