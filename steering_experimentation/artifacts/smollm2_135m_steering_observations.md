# SmolLM2-135M steering observations

## Motivation

We tested `HuggingFaceTB/SmolLM2-135M` to determine whether activation steering
could provide formality control in a substantially smaller and cheaper model than
the existing `Qwen2.5-0.5B-Instruct` experiment. A successful result would make
local steering more practical on limited hardware while avoiding task-specific
fine-tuning.

The formality direction was learned from 8,000 GYAFC formal-minus-informal pairs.
Candidate geometry was evaluated on a disjoint 2,000-pair GYAFC holdout. Final
generation used the 35-record workplace sample at alpha 1 and alpha 2.

## What we observed

The automatically selected `layer10_mean` direction has strong representational
separation on GYAFC: 94.15% held-out pair-ordering accuracy. However, this did
not translate into strong causal control during generation. At alpha 1, 51.4%
of the sample outputs were exact copies; at alpha 2, 40.0% were exact copies.
Thirty of 35 inputs produced the same output at both strengths. The model often
retained the original hostile or informal wording, so the visible formalization
effect was weak even though the direction was geometrically clear.

`layer16_final_token` produced a much more visible intervention, but the change
was mostly excessive deletion and semantic damage rather than controlled
formalization:

| Metric | alpha 1 | alpha 2 |
|---|---:|---:|
| Exact-copy rate | 22.9% | 0.0% |
| Mean word overlap | 68.5% | 32.9% |
| Critical-value recall | 85.2% | 52.4% |
| Critical-value exact rate | 77.1% | 37.1% |
| Missing critical values | 10 | 29 |

At alpha 2 the model frequently dropped requested actions, names, dates, rooms,
and numeric constraints. It also changed facts: `$600, not $900` became a budget
of `$900`, and several responses became repetitive or incoherent. Alpha 1 was
less destructive, but still removed important clauses and sometimes reversed
relationships between values.

## Comparison with Qwen

The earlier Qwen experiment showed a more recognizable and ordered formality
trajectory. Positive steering expanded contractions, regularized punctuation,
and introduced more formal vocabulary. Its outputs changed progressively with
alpha, making the causal effect easier to interpret. Qwen also lost meaning at
strong settings—especially alpha 1 and alpha 2—so it was not free of the same
trade-off, but its changes were more consistently related to formality.

SmolLM2-135M instead showed two less useful regimes:

1. `layer10_mean`: little or no visible change.
2. `layer16_final_token`: obvious change, but primarily truncation, repetition,
   and loss of facts rather than reliable formalization.

This is not a perfectly controlled model-to-model comparison. The Qwen model is
an instruction-tuned 0.5B model, while the tested SmolLM2 checkpoint is a 135M
base model. The saved Qwen qualitative sweep also used held-out GYAFC inputs,
whereas the final SmolLM generation analysis used the harder workplace sample.
The result therefore reflects both model capacity and instruction-tuning
differences, not model size alone.

## Conclusion

The lightweight-model objective was not achieved with the base
SmolLM2-135M checkpoint under this steering protocol. The model contains a
measurable formality direction, but it does not convert that direction into a
useful balance of style change and meaning preservation. Compared with Qwen,
SmolLM2-135M either under-steers or becomes destructive, depending on the layer.

For the next lightweight experiment, the strongest options are to test
`SmolLM2-135M-Instruct` or `SmolLM2-360M-Instruct`, run a denser and smaller alpha
sweep, and select candidates using causal generation quality rather than
representation separation alone. A separate ParaDetox direction would still be
required for detoxification; the GYAFC direction measures formality only.

