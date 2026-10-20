---
team: SecondThought
session: "07"
date: 2026-10-20
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

- Added a comparison interface for three approaches: detox fine-tuning, formality fine-tuning, and combined steering (PR #24 and PR #25).
- Added reliable local loading and generation for both fine-tuned T5 models.
- Combined formality and detoxification steering in one Qwen response, with separate alpha and beta controls and warnings for unsafe settings (PR #25).
- Added a minimal-rewrite instruction that asks Qwen to preserve facts, names, deadlines, actions, and intent.
- Tested detoxification steering across layers and strengths, then selected Layer 11 and oriented beta so positive values reduce toxicity.
- Trained one T5-small model on both ParaDetox and GYAFC. Mixed training and separate task prefixes help it retain both detoxification and formalization skills (PR #26).
- Prevented duplicate inputs from leaking across data splits and evaluated the two tasks separately.
- Added two-stage inference that detoxifies a message and then formalizes the result, while saving the intermediate output.
- Evaluated the combined fine-tuned pipeline on all 35 workplace messages and saved the results in `outputs/both_detox_formalize.csv`.
- Updated project dependencies for the new training and steering experiments.



## Training results

### Approach

- Trained one 60.5M-parameter T5-small model from its base checkpoint for two tasks: `detoxify:` using ParaDetox and `formalize:` using GYAFC.
- Mixed and shuffled 120,349 training pairs so both tasks appeared throughout training instead of one overwriting the other.
- Split ParaDetox by unique input and removed 37 GYAFC evaluation sentences that also appeared in training.
- Kept separate held-out test sets for detoxification and formalization.

### Training run

- Trained for 3 epochs on one A100 GPU: 22,566 steps in approximately 54 minutes.
- Validation loss improved each epoch: 1.207, 1.167, then 1.159.
- The final epoch was selected automatically as the best checkpoint.

### Held-out results

- ParaDetox test loss: 0.898, compared with approximately 0.91 for the detox-only model.
- GYAFC test loss: 1.159, compared with approximately 1.16 for the formality-only model.
- GYAFC four-reference BLEU: 75.07, versus 50.07 when copying the input unchanged.
- The same sentence produced different outputs under the two prefixes, confirming that the model retained distinct detoxification and formalization behaviours.

One jointly trained model therefore retained both skills at roughly the performance of the separate models. Whether using both skills improves workplace rewrites is evaluated separately below.

## Workplace metrics snapshot

The combined fine-tuned pipeline was tested on 35 workplace messages by applying `detoxify:` first and `formalize:` second.

| Metric | Result |
| --- | ---: |
| Mean toxicity | 0.604 → 0.060 |
| Reduction between mean toxicity scores | 90.0% |
| Mean per-message relative toxicity reduction | 80.6% |
| Mean semantic similarity | 0.955 |
| Minimum semantic similarity | 0.770 |
| Critical values preserved | 44/45 |
| Unsupported critical values | 3 |
| Messages with exact critical-value preservation | 33/35 |
| Mean edit ratio | 0.080 |
| Mean length ratio | 0.938 |
| Exact copies | 2/35 |
| Mean CPU latency | 326 ms |

Most outputs removed explicit insults while retaining the main request and structured details:

| Original | Combined rewrite | Observation |
| --- | --- | --- |
| “Who the hell sent the boxes to 47 Willow Lane? They were supposed to go to 92 Cedar Court.” | “Who sent the boxes to 47 Willow Lane? They were supposed to go to 92 Cedar Court.” | Removed hostility and preserved both addresses. |
| “This lazy crap has cost us 2 hours already. Restart the scanner and call Priya if it fails again.” | “This has cost us two hours already. Restart the scanner and call Priya if it fails again.” | Preserved the duration, action, and contact. |
| “That report is garbage. The defect rate went from 2.5% to 4%...” | “That report is bad. The defect rate went from 2,5% to 4%...” | Changed decimal punctuation, causing a critical-value failure. |
| “What a ridiculous pile of nonsense. Remove the made-up claims from the proposal before it goes out.” | “Remove the made-up claims from the proposal before it goes out.” | Preserved the action but deleted the criticism instead of rewriting it. |

The pipeline removes explicit toxicity and usually preserves numbers, dates, and amounts. Its remaining failures are under-rewriting, deleting criticism, and occasionally changing structured details. The current automatic metrics also cannot determine whether an output is genuinely professional and ready to send.


## User / validation learning

- Good test scores do not always produce better workplace messages.
- Rewriting twice is slower and can change important details.
- A low toxicity score does not guarantee that a rewrite is clear, accurate, or useful.
- We still need a reliable way to measure professionalism and formality.



## Integration and evaluation blockers

- A duplicate `ComparisonRewriter` definition breaks the app's alpha/beta generation call.
- The combined T5 model works in batch inference but is not yet available in the comparison interface.
- Tests and evaluation experiments are ignored by Git; the local tests currently fail, and there is no shared end-to-end comparison script.
- Some result metadata uses developer-specific paths, and the README does not fully document the new workflow.
- The 35-message set lacks reference rewrites, detailed labels, clean controls, fixed pass thresholds, and human review. Because it was also used to choose settings, it is a development set rather than a final test set.



## Next session goals

1. Fix the comparison app and restore a passing, version-controlled test suite.
2. Add the combined T5 model to the interface and choose how its two tasks should be presented.
3. Create one shared evaluation command for every model and record enough information to reproduce each run.
4. Add formality scoring and human review for the strongest models.
5. Improve the workplace dataset with detailed labels, professional control messages, and a separate final test set.
6. Compare all model options on the same test set, then run external sendability trials with the best candidates.



## Individual contributions

- princeixr: integrated the two existing fine-tuned T5 outputs into the comparison interface; developed the ParaDetox hidden-state and causal steering experiments; selected and packaged the Layer 11 detoxification direction; implemented simultaneous Layer 4 formality and Layer 11 detoxification steering with independent alpha/beta controls; added the fixed preservation-oriented prompt and steering warnings (PR #24 and PR #25).

- ayman-tech: developed and ran the joint ParaDetox/GYAFC T5-small training notebook; preserved task separation with exact prefixes and mixed batches; reported separate task losses and GYAFC BLEU; extended batch inference to ordered task pipelines; generated and evaluated the 35-message combined fine-tuned output; merged the model-comparison and steering work (PR #24, PR #25, and PR #26).

- moziyadh110: Experimented with ParaDetox → GYAFC two-stage fine-tuning pipeline; completed Stage 1 (paradetox FineTuning), passed the Stage 2 (GYAFC fineTuning on top of stage 1 model) smoke test. Also merged PR #26.

- SAI-RAHUL-M: built and tested the Chrome extension and local API server with status checks, error handling, and selected-text support (PR #5). Later replaced the OpenAI backend with a fully local two-stage T5 pipeline, which preserved 95.6% of critical values at about 0.77 seconds per message on the workplace set (PR #27).



## Lean canvas changes

- **Solution:** SecondThought now has two technical strategies for joint control: independent activation steering on Qwen and prefix-conditioned multi-task fine-tuning on T5-small.
- **Value proposition:** the evaluation reinforces that “less toxic” is not enough. The product must produce a message that is professional and sendable while preserving the complaint, action, urgency, and facts.
- **Key metric:** corpus loss and BLEU are training diagnostics. The release metric should become human-validated workplace task success, supported by automatic toxicity, critical-fact, action-preservation, and stability gates.
- **Cost structure:** the local multi-task model keeps both tasks in one 60M-parameter checkpoint, but sequential inference doubles generation work. Combined steering uses one generation but loads a larger causal model and currently has weaker preservation.
- **Primary risk:** neither architecture has yet demonstrated a clear product-level improvement. Formality is unmeasured, the benchmark is small and reused for tuning, and the current UI integration is broken.
