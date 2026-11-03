---
team: SecondThought
session: "09"
date: 2026-11-03
members:
  - name: Nandan Prince
    github: princeixr
    hat: Data&Eval
  - name: Ayman Sayed
    github: ayman-tech
    hat: Engineering
  - name: Sai Rahul Meda
    github: SAI-RAHUL-M
    hat: Product
  - name: Mohamed Ziyadh
    github: moziyadh110
    hat: Users&Research
---

# SecondThought: Weekly Report

## Shipped this session

- Fine-tuned SmolLM2-135M on ParaDetox and GYAFC together, as a decoder-only candidate for edge devices. The train and inference notebooks are now architecture-agnostic: one setting switches between encoder-decoder (T5) and decoder-only models (PR #44).
- Compared SmolLM2 with `both-t5` on 52 sentences (35 workplace messages plus 17 probes), saved in `outputs/smallm_vs_t5.csv` (PR #44).
- Added a model- and feature-agnostic activation-steering framework that runs the same experiment across causal language models and paired-text features, and used it to test SmolLM2-135M as a lightweight alternative to Qwen (PR #43).
- Prototyped the "sendable gate", which gives each rewrite one verdict and a reason for failure, instead of an average score (PR #42).
- Prototyped a shadow post-rewrite checker that verifies facts, hostility and requests, repairs what it safely can and warns about the rest. It runs separately from the product (PR #42).
- Fixed the problems found while using the nudge in live Gmail (PR #41):
  - Shouted insults are now lowercased before the model runs, while real acronyms stay intact.
  - Replace changes only flagged lines, leaving signatures, quoted replies and formatting untouched, and one Undo restores the draft.
  - The suggestion card shows only real changes and warns when a harsh word remains.
  - A dismissed pill returns on a new harsh sentence.

## SmolLM2-135M fine-tuning results

### Why SmolLM2

- The goal is edge-device support. In bf16, SmolLM2-135M is about 270 MB (roughly 300 MB of RAM on CPU in our test), compared with about 1 GB for Qwen2.5-0.5B.
- Being decoder-only also makes it a good fit for activation-steering experiments.
- Zero-shot it cannot do the task: it replies like a chatbot instead of rewriting.

### Training run

- Mixed ParaDetox and GYAFC (120,349 training pairs) with the `detoxify:` and `formalize:` prefixes. Each example is one sequence of prompt plus rewrite, with the loss on the rewrite only.
- Used fp32 weights with bf16 mixed precision at a learning rate of 5e-5, and exported in bf16.
- The run took about 35 minutes. Validation loss was 1.077, 1.082, then 1.132 across three epochs, so the first epoch was selected as the best checkpoint.

### Held-out results

| Metric | SmolLM2-135M | `both-t5` (session 7) |
| --- | ---: | ---: |
| Trainable parameters | 134.5M | 60.5M |
| ParaDetox test loss | 0.912 | 0.898 |
| GYAFC test loss | 1.051 | 1.159 |
| GYAFC four-reference BLEU | 76.36 | 75.07 |
| Copy-the-input BLEU | 50.07 | 50.07 |

Test losses come from different architectures, so they are not directly comparable. BLEU is the fairer comparison, and it only measures formalization.

### Side-by-side rewrites

Both models ran `detoxify:` and then `formalize:`.

| Original | `both-t5` | SmolLM2-135M | Observation |
| --- | --- | --- | --- |
| "You dumped 18 broken laptops on my desk like an idiot..." | "You dumped 18 broken laptops on my desk..." | "You dumped 18 broken laptops on my desk like an idiot..." | SmolLM2 left the insult in. |
| "I'm sick of your bullshit excuses, Daniel..." | "I am sick of your excuses Daniel..." | "I am sick of your excuses, Daniel..." | Both removed the swear word; SmolLM2 kept the punctuation. |
| "gonna need that report asap, u totally dropped the ball on this one" | "I'm going to need that report as soon as possible. You totally dropped the ball on this one." | "You need that report as soon as possible, you totally dropped the ball on this one." | SmolLM2 changed who needs the report. |

Formalization looks good on both. In the rows inspected, SmolLM2 sometimes dropped content or left insults in. These are inspected examples, not a metric comparison.

## SmolLM2-135M steering results

Formality directions were learned from 8,000 GYAFC pairs and ranked on a disjoint 2,000-pair holdout across all 30 decoder layers, then tested on the 35 workplace messages.

| Metric | `layer10_mean` alpha 1 | `layer10_mean` alpha 2 | `layer16_final_token` alpha 1 | `layer16_final_token` alpha 2 |
| --- | ---: | ---: | ---: | ---: |
| Exact-copy rate | 51.4% | 40.0% | 22.9% | 0.0% |
| Mean word overlap | 85.6% | 80.3% | 68.5% | 32.9% |
| Critical-value recall | 98.6% | 95.2% | 85.2% | 52.4% |
| Messages with exact critical values | 97.1% | 91.4% | 77.1% | 37.1% |
| Missing critical values | 1 | 4 | 10 | 29 |

- `layer10_mean` separates formal from informal text well (94.15% held-out ordering accuracy), but barely changes the generated text. 30 of 35 inputs gave the same output at both strengths.
- `layer16_final_token` steers more strongly, but mostly by deleting facts, numbers and requested actions. At alpha 2, "$600, not $900" became a budget of $900.
- Compared with Qwen's more consistent formality trajectory, the base 135M model either under-steers or becomes destructive, so it is not yet suitable for lightweight steering. Qwen was an instruction-tuned 0.5B model, so this reflects instruction tuning as well as size.

## Sendable gate results

The gate asks one question per rewrite: would you send this as-is? It also records why a rewrite fails: still rude, facts changed, meaning lost, or simply copied. Intent and "nothing added" checks are not built yet and thresholds are placeholders, so every verdict is provisional.

| System | Toxicity after | Sendable | Copied | Facts changed | Still hostile | Content lost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ParaDetox T5 | 0.056 | 25/35 | 4 | 0 | 7 | 3 |
| `both-t5`, session 7 pipeline | 0.060 | 24/35 | 2 | 2 | 8 | 1 |

A rewrite can fail more than one check. Rewrites that score well on the old metrics can still be unsendable: ParaDetox T5 has 100% exact facts and 84% relative toxicity reduction, yet 10 of its 35 rewrites fail.

The shadow checker was run on the `both-t5` rewrites from the session 7 pipeline. Of the 11 unsendable rewrites, it fixed 2 and flagged the other 9. It is not part of the product.

## User / validation learning

- No user trials yet, so there is no user-derived learning this session.
- Using the nudge in live Gmail exposed problems the automated checks had missed: shouted insults, signatures being rewritten, and suggestions that looked like a word was replaced by itself.
- A geometrically clear steering direction does not guarantee useful generation. `layer10_mean` scored 94% on ordering and barely changed the text.
- Fixes around a model can stop it damaging a message, but cannot make it write better. `both-t5` still leaves "You are lazy" and "Did you even test this?" unchanged, and the card now says so.

## Evaluation blockers

- The sendable gate has no human labels, so its thresholds cannot be fitted and its verdicts remain provisional.
- SmolLM2 has been inspected by reading rows, not scored with the evaluation metrics.
- The shadow checker ran on saved session 7 rewrites, not on the current product pipeline.
- The 35-message set is still a development set, used for tuning settings and the nudge's trigger list.
- Carried over: the duplicate `ComparisonRewriter` in the comparison app, the tests ignored by Git, and the missing shared end-to-end evaluation command.

## Next session goals

1. Score SmolLM2 with the same metrics and sendable gate as `both-t5`, and try longer training.
2. Label about 100 rewrites with "Would you send this to your manager as-is?" and fit the gate's thresholds to those labels.
3. Finish the gate's missing intent and "nothing added" checks, and run it on the current product pipeline.
4. Decide whether the shadow checker's repairs and warnings should move into the product.
5. Test `SmolLM2-135M-Instruct` or `SmolLM2-360M-Instruct` for steering, selecting candidates by generation quality rather than separation alone.
6. Test the nudge on the live Slack site and run the first user trials through it.
7. Fix the carried-over app and test issues.

## Individual contributions

- SAI-RAHUL-M: used the in-page nudge in live Gmail, found several problems, and fixed them by improving how the extension handles the model's input and output, without changing the model itself (PR #41). Shouted insults such as "IDIOT!" and "This is GARBAGE." used to slip through, because the model barely reacts to ALL-CAPS text and the facts guard protected those words as acronyms; shouted words are now lowercased before the model runs, using the tokenizer's vocabulary to keep real acronyms such as GDPR and API intact, and insult-only sentences are dropped when the message says something else too. Replace used to rewrite the whole text box, which damaged signatures, doubled blank lines and lost formatting; it now skips signatures and quoted replies and changes only the lines that set off a trigger, and one Undo restores the full draft. The suggestion card now separates words from punctuation, so it shows only real changes, and it warns when a harsh word remains ("Still sounds harsh: lazy") instead of presenting that as a finished rewrite. A dismissed pill now returns on a new harsh sentence or when the user comes back to the text box. Critical-value preservation stayed at 45/45 and mean toxicity at 0.102 on the 35 workplace messages, 31/31 automated UI checks passed against the real `both-t5` model, and the Replace fix was confirmed on a real draft in live Gmail.

- moziyadh110: built and tested two prototypes (PR #42).
  - Sendable gate: a stricter evaluation that gives each rewrite one verdict, would you send this as-is, and records why it fails: still rude, facts changed, meaning lost, or simply copied. On the 35 workplace messages, it showed that rewrites scoring well on the old metrics can still be unsendable.
  - Post-rewrite checker: compares each rewrite with the original, checks that facts were kept, rude phrases were removed and requests survived, then fixes what it safely can and warns about the rest. On the `both-t5` rewrites from the session 7 pipeline, 11 of 35 were not sendable; the prototype fixed 2 and flagged the other 9. It ran separately from the product and is not part of it.

- ayman-tech: chose SmolLM2-135M for edge-device support, at about 270 MB in bf16 (roughly 300 MB of RAM on CPU) compared with about 1 GB for Qwen2.5-0.5B, and because being decoder-only suits activation-steering experiments. Since it cannot do the task zero-shot, fine-tuned one model for both jobs on about 120k mixed ParaDetox and GYAFC pairs with the `detoxify:` and `formalize:` prefixes, using one prompt-plus-rewrite sequence per example with the loss on the rewrite only, fp32 weights with bf16 mixed precision at a learning rate of 5e-5, and a bf16 export, in about 35 minutes of training. Made the train and inference notebooks architecture-agnostic, so a single setting switches between encoder-decoder and decoder-only models. Ran 52 sentences (35 workplace messages plus 17 probes, including a long one) through SmolLM2 and the multi-task T5, each through detoxify then formalize. Formalization looks good on both; in the rows inspected, SmolLM2 sometimes dropped content or left insults in, so next steps are longer training and proper metrics (PR #44).

- princeixr: designed, implemented and merged a model- and feature-agnostic activation-steering framework for running consistent experiments across different causal language models and paired-text features. The framework supports GYAFC, ParaDetox, Hugging Face datasets and custom CSV/JSONL data; extracts target-minus-source activation directions; evaluates mean-pooled and final-token candidates across every decoder layer; and records generated outputs alongside meaning- and critical-value-preservation diagnostics. Used it to investigate SmolLM2-135M as a lightweight alternative to Qwen, learning formality directions from 8,000 GYAFC pairs and ranking candidates on a disjoint 2,000-pair holdout before testing `layer10_mean` and `layer16_final_token` on the 35 workplace messages at alpha 1 and 2. The experiments found that `layer10_mean` encoded formality geometrically but produced little visible generation change, while `layer16_final_token` steered more strongly but frequently deleted facts, numbers and requested actions. Compared with Qwen's more consistent formality trajectory, SmolLM2-135M either under-steered or became semantically destructive, showing that the 135M base model is not yet suitable for the project's lightweight steering objective. Merged the reusable framework, candidate artifacts, generated outputs, evaluation summaries and documented negative findings into master (PR #43).

## Lean canvas changes

- **Cost structure:** SmolLM2-135M brings the edge-device path closer at about 300 MB of RAM on CPU, compared with about 1 GB for Qwen. It is not yet good enough to replace `both-t5`, which stays live in the extension.
- **Solution:** fine-tuning remains the working route on small models. Steering on the 135M base model either under-steers or destroys meaning.
- **Key metric:** the sendable gate is the first candidate for one product-level verdict per rewrite, but it needs human labels before it can be the release metric.
- **Value proposition:** the product can now be honest about its limits. The nudge warns when a harsh word remains, and the shadow checker explores extending that to facts and requests.
- **Primary risk:** still no real users. Every result so far comes from our own 35-message development set and our own use of the nudge.
