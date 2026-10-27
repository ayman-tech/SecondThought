# FLAN-T5 size steering experiment

## Question

Does a larger encoder–decoder model make activation steering more effective and less likely to change the message's context?

## Controlled setup

The existing FLAN-T5-small experiment was repeated with `google/flan-t5-base`.
Only the checkpoint and extraction batch size changed.

| Setting | FLAN-T5-small | FLAN-T5-base |
| --- | ---: | ---: |
| Parameters | 77.0M | 247.6M |
| Encoder blocks | 8 | 12 |
| Decoder blocks | 8 | 12 |
| Hidden size | 512 | 768 |

Both runs used the same:

- 2,000 extraction and 500 held-out pairs per feature;
- GYAFC formality and ParaDetox detoxification pairs;
- split seed and workplace inputs;
- fixed rewrite prompt and four-beam decoding;
- alpha/beta grid `{0, 1, 2}`;
- toxicity, semantic-similarity, and critical-value evaluators.

The base run selected decoder block 7 for formality and block 11 for
detoxification. Held-out ordering accuracy was 100.0% and 99.8%, respectively.

## Results

| Condition | Model | Output toxicity ↓ | Similarity ↑ | Critical values | Changed outputs |
| --- | --- | ---: | ---: | ---: | ---: |
| `(0, 0)` | Small | 0.5649 | 0.9713 | 45/45 | 0/35 |
| `(0, 0)` | Base | **0.4996** | **0.9792** | **45/45** | 0/35 |
| `(0, 2)` | Small | 0.5496 | 0.9924 | 44/45 | 8/35 |
| `(0, 2)` | Base | 0.4996 | 0.9792 | **45/45** | **0/35** |
| `(1, 0)` | Small | 0.5142 | 0.9769 | 44/45 | 4/35 |
| `(1, 0)` | Base | **0.4744** | 0.9729 | **45/45** | 5/35 |
| `(2, 2)` | Small | **0.4690** | **0.9814** | 44/45 | 12/35 |
| `(2, 2)` | Base | 0.4882 | 0.9695 | **45/45** | 8/35 |

Every base-model condition preserved all 45 automatically tracked critical
values and introduced no unsupported structured values. This is an improvement
over the small-model run.

The base model did not respond to detoxification steering: beta 1 and beta 2
changed 0 of 35 outputs. Formality steering changed 5 outputs at alpha 1 and 8
at alpha 2. The strongest small-model mixture changed 12 outputs.

## Qualitative findings

Some base-model changes were useful:

- `Who the hell sent...` became `Who sent...` while preserving both addresses.
- `This invoice is a damn mess` became `This invoice is a mess`, while preserving
  both amounts and the request.

Other changes still damaged context:

- `...so fix the quote` was deleted from one output.
- `Call them back` was deleted from another.
- One output removed the name `Daniel` and restored the word `bullshit`.
- Another removed `Nina`, weakening who the message was about.

The critical-value metric did not catch these failures because requested actions
and ordinary person names are not annotated in the current dataset.

## Conclusion

The size hypothesis is **partly supported**. FLAN-T5-base provides a cleaner
unsteered baseline and stronger structured-value preservation, but model size
alone does not make activation steering stronger or reliably safer. Under the
same protocol, the detoxification direction has no observable generation effect,
and formality steering can still delete actions or participants.

The main limitation is now the steering method rather than only model capacity.
Layer selection currently rewards how well a direction separates paired hidden
states, not whether intervening on that layer produces useful text. For the base
model, the selected detox direction has excellent separation but a very small raw
norm and no causal response at beta 1 or 2.

## Overall T5 steering assessment

### What we tested

We first tested combined formality and detoxification steering on
FLAN-T5-small, then repeated the controlled experiment with the larger
FLAN-T5-base model. Directions were extracted from paired GYAFC and ParaDetox
examples and added to decoder hidden states during generation. Both models used
the same prompt, workplace messages, deterministic decoding, and automatic
evaluation.

The larger-model follow-up tested several formality directions instead of
trusting a single layer selected from hidden-state separation. Four decoder
directions were evaluated at strengths 0.5, 1, 2, and 4 on 100 GYAFC tune
examples with human references and the 35 workplace messages. The detailed
results are in `t5_formality_experiment_results.md`.

### What we observed

- **Good direction geometry did not guarantee useful control.** Some directions
  separated formal and informal examples almost perfectly but caused no change
  in generated text. The selected base-model detox direction changed 0/35
  workplace outputs at beta 1 and beta 2. A strong layer-11 formality direction
  also changed 0/35 outputs at every tested strength.
- **Safe strengths had little visible effect.** The best formality setting,
  decoder layer 10 at strength 1, changed only 3/35 workplace outputs. It raised
  GYAFC BLEU from 49.11 to 51.63, but the improvement was small and
  input-dependent.
- **Internal changes did not reliably become text changes.** A diagnostic check
  confirmed that the layer-10 hook ran and substantially changed hidden states
  and output logits. Even so, some inputs produced exactly the same decoded text
  from strength 0 through 2 because the highest-ranked tokens did not change.
- **Strong steering was unstable.** At strength 4, layer-10 BLEU fell to 30.83
  and layer-7 BLEU fell to 19.05. Outputs repeated phrases, omitted requests,
  switched who was responsible for an action, or generated unrelated text.
  Layer 7 preserved only 35/45 tracked critical values at this strength.
- **A larger model did not solve the control problem.** FLAN-T5-base had a
  cleaner unsteered baseline than FLAN-T5-small, but it did not make steering
  consistently stronger, safer, or more predictable.
- **The automatic preservation checks were incomplete.** They could verify
  numbers, dates, and amounts but missed deleted actions and ordinary names such
  as Daniel or Nina. Average similarity therefore understated important product
  failures.

### Why this is a poor fit for our objective

Our product needs a control that produces a clear, gradual improvement in
professionalism while reliably preserving meaning, people, values, and requested
actions. The tested T5 intervention instead behaved like a threshold: it often
did nothing at moderate strengths and became destructive when increased.

The encoder–decoder structure is a likely contributor. The source message is
represented in the encoder, while the direction is added to the separate decoder
stream that generates the rewrite. A constant late-decoder shift must compete
with cross-attention to the source and subsequent normalization. It can change
token probabilities without changing the selected tokens; once it is strong
enough to override them, applying it again at every generation step can compound
into repetition or semantic drift. Directions extracted under teacher forcing
also do not necessarily transfer cleanly to free generation.

These mechanisms are an interpretation of our results, not proof that all
encoder–decoder steering is ineffective. Encoder steering, learned
interventions, or jointly calibrated encoder and decoder controls could behave
differently. However, simple additive decoder steering on FLAN-T5-small and
FLAN-T5-base is not a good product candidate for the current objective.

## Decision

FLAN-T5 steering has been removed from the comparison application. The scripts,
artifacts, generated outputs, and reports are retained as a negative research
result. Product evaluation should focus on the fine-tuned T5 models and the
decoder-only Qwen approaches, where steering has a clearer effect on generation.

If T5 steering is revisited, it should be treated as a new research track with
causal layer selection, separately calibrated strengths, action/name annotations,
and blinded human ratings—not as a near-term application model.
