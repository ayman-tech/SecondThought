---
team: SecondThought
session: "08"
date: 2026-10-27
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

- Switched the local API and Chrome extension to our own jointly trained `both-t5` model. Each sentence runs through `detoxify:` and then `formalize:` on one T5-small, so nothing leaves the machine and no API key is needed (PR #31).
- Added a facts guard to the T5 rewriter. If a step drops or changes a number, date, amount or similar value, that sentence keeps its previous wording. On the 35 workplace messages this raised critical-value recall from 93% to 100% (45/45); for example, "2.5%" no longer becomes "2,5%" (PR #31).
- The T5 rewriter now loads each model folder only once, so `both-t5` serves both steps from one copy in memory (PR #31).
- Added the in-page "SecondThought?" nudge on Gmail, Slack, Teams, Outlook, LinkedIn and GitHub. A small pill appears while typing when the message contains swearing, insults, texting shorthand or shouting (PR #32).
  - Detection runs inside the page with a word list and a few patterns, about 0.6 s after typing stops. Nothing is sent to the model until the user clicks the pill.
  - Clicking shows the suggestion with removed words struck out and new ones highlighted, plus Replace (with Undo), Copy and Dismiss.
  - Selecting part of a message rewrites only that part, and the nudge can be switched off per site from the popup.
  - Tested in live Gmail, and passes 15/15 automated UI checks.

### The nudge in live Gmail

| 1. Pill appears while typing | 2. Suggestion with word-level diff | 3. After Replace, with Undo |
| :---: | :---: | :---: |
| <img width="1097" height="1100" alt="image0" src="https://github.com/user-attachments/assets/f9e773f8-1d35-4e58-823c-1f2ee61d1b02" />| <img width="1095" height="1118" alt="image1" src="https://github.com/user-attachments/assets/8e38eade-48a5-4365-95e1-04c501d9fd37" />| <img width="1079" height="1102" alt="image2" src="https://github.com/user-attachments/assets/8883ca38-e768-4513-b99f-5afc68136337" />|

- Completed the full ParaDetox → GYAFC two-stage training run and measured its effect on detoxification (results below).
- Started designing the evaluation metric. Reviewed how the ParaDetox and GYAFC papers evaluate their tasks, catalogued the failures our current metrics miss, and wrote up the project context, data schemas and evaluation methods as a shared brief for the metric design.

## Two-stage training results (ParaDetox → GYAFC)

A sequential alternative to the jointly trained model: t5-small on ParaDetox, then that model fine-tuned on GYAFC. Each stage ran 3 epochs at lr 1e-4 on a T4 GPU.

| | Stage 1: ParaDetox | Stage 2: GYAFC |
| --- | ---: | ---: |
| Validation loss by epoch | 0.987 → 0.954 → 0.945 | 1.332 → 1.300 → 1.292 |
| Test loss | 0.943 | 1.202 |
| GYAFC BLEU (4 refs) | n/a | 73.47 (copy baseline 50.07) |
| Outputs identical to input | n/a | 4.4% |

The same workplace messages, with the `detoxify:` prefix, before and after stage 2:

| Insult | After stage 1 | After stage 2 |
| --- | --- | --- |
| "a damn mess" | removed | removed |
| "like an idiot" | removed | returned |
| "bullshit excuses" | removed | returned |
| "This stupid retry loop" | removed | returned |

- Stage 2 learned formality well, but it overwrote most of the detoxification learned in stage 1.
- After stage 2, `detoxify:` and `formalize:` produce identical outputs, so the model no longer separates the tasks.
- GYAFC's formal references keep offensive content (e.g. "idiots"), so stage 2 trains the model to keep insults.
- This confirms the session 7 choice of mixed training over sequential training: the last stage overrides the earlier one.
- The jointly trained `both-t5` beats it on both tasks (GYAFC BLEU 75.07 vs 73.47) while keeping detoxification.

## User / validation learning

- No user trials yet, so there is no user-derived learning this session.
- The nudge's trigger list is hand-written, and some insults were added after looking at our own 35-message set. It will miss new kinds of hostility such as sarcasm and passive aggression.
- The nudge was tested in live Gmail. Slack was tested only on a stand-in page; its editor is complex, so Replace still needs a real-world check there.
- The facts guard only protects values the extractor can find. Meaning changes in plain words still get through, e.g. "b4 the mtg" became "with the Mtg".
- Reviewing the literature showed that both reference datasets combine content preservation and fluency with a task score, and check their automatic metrics against human ratings. Our metrics are still reported separately and have not been checked against people.

## Evaluation blockers

- Formality, fluency and preservation of the requested action are still unmeasured.
- Detoxify misses hostility without swear words, such as "Did you even test this?".
- There are no human labels, so metric thresholds can't be chosen and no metric has been checked against human judgment.
- The 35-message set is a development set. It was used to tune settings and to write the nudge's trigger list, so it can't serve as a final test.
- Carried over from session 7: the duplicate `ComparisonRewriter` in the comparison app, the tests ignored by Git, and the missing shared end-to-end evaluation command.

## Next session goals

1. Collect every known failure case (word swaps, deleted criticism, hostility without swear words, changed values) into one file for checking candidate metrics.
2. Label about 100 rewrites with "Would you send this to your manager as-is?" plus checks for the request, facts and tone, and measure agreement between raters.
3. Check which automatic metrics agree with those labels, then add only the missing pieces, such as a formality classifier, a fluency score and a check that the requested action survived.
4. Score the two-stage model on the 35 workplace messages for a direct comparison with `both-t5`.
5. Test the nudge on the live Slack site and run the first user trials through it.
6. Fix the carried-over app and test issues.

## Individual contributions

- SAI-RAHUL-M: moved the Chrome extension onto the multi-task `both-t5` model and added a facts guard that undoes any step that changes a number, date or amount, taking critical-value preservation to 45/45 on the workplace set (PR #31). Built an in-page "SecondThought?" nudge that spots heated or overly casual wording locally as you type in Gmail, Slack and similar sites, and offers a rewrite with a word-level diff plus Replace, Copy and Undo; tested in live Gmail and with 15/15 automated UI checks (PR #32).
- moziyadh110: started the evaluation-metric design by reviewing the ParaDetox and GYAFC evaluation methods, cataloguing current metric gaps, and writing a shared project brief of the data schemas, evaluation methods and literature; reviewed and merged PR #31.
  - Wrote an evaluation related-work review (GYAFC, ParaDetox, style-transfer metric and LLM-as-judge studies) and proposed a "sendable gate": six pass/fail checks per rewrite (not a copy, facts intact, hostility gone, intent kept, nothing lost or damaged, nothing added and still fluent), with thresholds calibrated on human "Would you send this to your manager as-is?" labels and systems compared by their sendable rate.
- ayman-tech: reviewed and merged PR #32. Also experimented steering with combination of Fine-Tuned models.
- princeixr: FLAN-T5 activation-steering experiment comparing flan-t5-small and flan-t5-base; extracted GYAFC formality and ParaDetox detoxification directions, evaluated candidate decoder layers and steering strengths against GYAFC references and 35 workplace messages, and verified that interventions changed internal activations even when decoded outputs remained unchanged. Found that safe strengths produced limited effects while stronger steering caused repetition, missing actions and semantic drift. Documented T5 steering as unsuitable for the current product objective and retained the scripts, artifacts and results as a negative research finding. Work remains on the `nandan/steering_T5` branch and is not being merged for now.

## Lean canvas changes

- **Channels:** the nudge is the first touchpoint inside the places people actually write messages. Users no longer need to open the popup.
- **Unfair advantage / privacy:** detection runs in the page and rewriting runs on a local model, so nothing leaves the machine. This is now a working default, not a plan.
- **Key metric:** still not defined in a way that matches what people judge. Building a human-checked "sendable" metric is the top priority for the next session.
- **Primary risk:** the trigger list was built from our own development set and hasn't been tried by real users, so the nudge may miss hostility in real messages or flag messages that are fine.
