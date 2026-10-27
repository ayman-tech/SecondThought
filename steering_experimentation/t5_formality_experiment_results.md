# FLAN-T5-base formality steering experiment

## Question

Can a GYAFC formality direction causally improve FLAN-T5-base rewrites without
changing their meaning?

## Setup

- Model: `google/flan-t5-base` (247.6M parameters, 12 decoder layers).
- Direction data: 2,000 GYAFC train pairs; 500 separate pairs for checking each
  direction.
- Candidate selection: the four layer/pooling directions with the strongest
  held-out separation.
- Steering strengths: 0.5, 1, 2, and 4, plus an unsteered baseline.
- Formality evaluation: 100 GYAFC tune inputs with four human rewrites each.
- Preservation evaluation: 35 workplace messages, semantic similarity, and
  critical-value checks.

This is a development experiment. The GYAFC tune set is used to compare
settings, so it is not a final held-out test.

## Results

| Direction | Strength | GYAFC BLEU ↑ | Workplace similarity ↑ | Critical values | Workplace outputs changed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unsteered | 0 | 49.11 | 0.979 | 45/45 | 0/35 |
| Layer 7, mean | 1 | 51.60 | 0.973 | 45/45 | 5/35 |
| **Layer 10, mean** | **1** | **51.63** | **0.980** | **45/45** | **3/35** |
| Layer 7, mean | 2 | 49.54 | 0.969 | 45/45 | 8/35 |
| Layer 10, mean | 2 | 49.24 | 0.983 | 45/45 | 4/35 |
| Layer 10, mean | 4 | 30.83 | 0.968 | 45/45 | 14/35 |
| Layer 7, mean | 4 | 19.05 | 0.784 | 35/45 | 27/35 |

Copying the original GYAFC text scores 45.72 BLEU. Layer 10 at strength 1 is
the strongest measured setting, narrowly ahead of layer 7 at strength 1. The
layer-11 direction changes no workplace outputs at any tested strength, despite
scoring well during direction extraction.

## Examples

Useful layer-10, strength-1 changes include:

- `call her and tell her how much you love her` → `Call her and tell her how
  much you love her.`
- `no dear its not a good idea ... u get a perfect partner` → `Its not a good
  idea ... you get a perfect partner.`
- `Maya, this invoice is a damn mess` → `Maya, this invoice is a mess`, while
  retaining `$480`, `$450`, and the requested action.

The same setting can still change meaning:

- `friend, spouse, or even your family members.` → `Have a good day.`

Strong steering is clearly unstable. At strength 4, outputs repeat phrases,
switch who performs an action, omit requests, and sometimes generate unrelated
text. For example, `You dumped 18 broken laptops ... Get them out ...` becomes
`You dumped 18 broken laptops ... I'll get them out ...` under layer 7.

## Conclusion

The formality direction has a real causal effect, but only in a narrow range.
FLAN-T5-base layer 10 at strength 1 improves reference BLEU by 2.52 points while
keeping average workplace similarity near the unsteered baseline. It is not yet
safe enough to use as a product setting because occasional meaning changes remain
and the workplace set has no direct human formality labels.

The experiment also confirms that representation separation is not sufficient
for layer selection: layer 11 separates formal and informal pairs but has no
observable generation effect. Future selection should use causal output quality,
with blinded human ratings for formality and meaning preservation.
