# Evaluating SecondThought: Related Work and Proposed Method

27 October 2026

## Abstract

Standard style-transfer evaluation scores style, meaning and fluency separately and averages them. In our runs, that hides messages that are still rude, lost their requested action, or were quietly damaged. We propose a **sendable gate**: six pass/fail checks per rewrite, with thresholds fitted to human answers to "Would you send this to your manager as-is?" A system is then judged by the share of rewrites a person would actually send.

## Related work

Prior work agrees on three things. Rewrites are judged on style, meaning and fluency. Automatic metrics only partly track human judgment. Any metric should be checked against human labels before it is trusted.

| Work | Finding | What we take |
| --- | --- | --- |
| [Rao & Tetreault 2018](https://arxiv.org/pdf/1803.06535) (GYAFC) | Humans rated formality, fluency, meaning and an overall ranking. The automatic meaning metric matched humans only weakly (Spearman 0.28) | Human labels per dimension; meaning metrics need checking |
| [Mir et al. 2019](https://aclanthology.org/N19-1049/) | Named three aspects: transfer intensity, content preservation, naturalness. Measuring content on style-masked text agreed better with humans. Systems trade one aspect against another | Mask insults before measuring meaning; report trade-offs, not one average |
| [Briakou et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.10668) | For formality, an XLM-R formality regressor and chrF track humans best for style and meaning. Treating style as a binary label is problematic | Use a learned formality score, not surface markers |
| [Logacheva et al. 2022](https://huggingface.co/datasets/s-nlp/paradetox/blob/main/README.md) (ParaDetox) | Scores style accuracy (Jigsaw toxicity classifier), similarity and fluency (CoLA classifier) | Same three axes; the CoLA fluency check |
| [ParaDetox joint score (as restated in SynthDetoxM 2025)](https://arxiv.org/pdf/2502.06394) | J = mean over sentences of STA × SIM × FL | A ranking score, not a decision |
| [Logacheva et al. 2022, HumEval](https://preview.aclanthology.org/setup/2022.humeval-1.8) | Automatic and manual detox metrics correlate only weakly, and least for the best models | Calibrate on our own human labels |
| [Zheng et al. 2023](https://arxiv.org/html/2306.05685v4) | A GPT-4 judge agreed with humans over 80% of the time, about the human-human level, but shows position, verbosity and self-preference bias | An LLM judge is usable if validated and kept off its own outputs |

## The gap

These metrics were built for sentence-level style change, not for workplace messages that must keep doing a job. Our t5-small run scored 84% toxicity reduction, 0.967 similarity and perfect value recall on 35 messages, yet:

- "I'm sick of your excuses, Daniel" passed: insults without swear words get past a Jigsaw-trained classifier.
- "a complete shitshow" → "a complete show" kept high similarity while the meaning broke.
- Hostile clauses were deleted, leaving outputs at 43% of the original length, and nothing flagged it.
- Copied toxic inputs scored perfect similarity and recall.
- No metric checks whether the requested action, urgency or "who owes whom" survived.

Averaging hides these failures, and a product score like J lets high similarity cover a lost fact.

## Proposed method: the sendable gate

Each rewrite gets one verdict, sendable or not, and must pass six checks in order. The first failure is recorded as the reason.

1. **Not a copy** of a hostile input.
2. **Facts intact:** no missing or invented numbers, dates, names or IDs.
3. **Hostility gone:** Detoxify plus a workplace hostility score, which catches rudeness without swear words.
4. **Intent kept:** an NLI model confirms the requested action, urgency, criticism and "who owes whom" still hold, using slots annotated once per input.
5. **Nothing lost or damaged:** every non-insult clause is covered, and no broken phrase remains where a swear word was deleted.
6. **Nothing added, still fluent:** no new praise, apology or claims, and a CoLA fluency check passes.

Already-professional messages pass only if they come back essentially unchanged.

**Calibration.** Two annotators label 150 rewrites (50 inputs × 3 systems) with "Would you send this to your manager as-is?" plus one question per check. Thresholds are fitted with grouped cross-validation to reach at least 90% precision on "sendable".

**Validation.** Each check is compared with its human question. The gate's agreement with humans is compared with agreement between the two annotators. A locked test set of new messages is scored once.

**Reporting.** Each system gets a sendable rate with a 95% interval and a count of failures per check. Systems are compared with McNemar's test.

**Borrowed vs new.** The three axes, style masking, CoLA fluency and validation against humans come from the works above. The gate, the intent and responsibility checks, the broken-phrase detector and the control check are our proposals.

## Sources

1. Rao, S. & Tetreault, J. (2018). Dear Sir or Madam, May I Introduce the GYAFC Dataset. NAACL. [arXiv:1803.06535](https://arxiv.org/pdf/1803.06535); correlations from the [supplementary notes](https://preview.aclanthology.org/fix_video/attachments/N18-1012.Notes.pdf)
2. Mir, R., Felbo, B., Obradovich, N. & Rahwan, I. (2019). Evaluating Style Transfer for Text. NAACL. [ACL Anthology N19-1049](https://aclanthology.org/N19-1049/)
3. Briakou, E., Agrawal, S., Tetreault, J. & Carpuat, M. (2021). Evaluating the Evaluation Metrics for Style Transfer. EMNLP. [arXiv:2110.10668](https://ar5iv.labs.arxiv.org/html/2110.10668)
4. Logacheva, V., Dementieva, D. et al. (2022). ParaDetox: Detoxification with Parallel Data. ACL. [Dataset card](https://huggingface.co/datasets/s-nlp/paradetox/blob/main/README.md)
5. Logacheva, V., Dementieva, D. et al. (2022). A Study on Manual and Automatic Evaluation for Text Style Transfer: The Case of Detoxification. HumEval. [ACL Anthology](https://preview.aclanthology.org/setup/2022.humeval-1.8)
6. SynthDetoxM (2025), restating the ParaDetox joint score J. [arXiv:2502.06394](https://arxiv.org/pdf/2502.06394)
7. Zheng, L. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS. [arXiv:2306.05685](https://arxiv.org/html/2306.05685v4)
8. Project results: SecondThought team runs (t5-small ParaDetox and GYAFC experiments, 35-message workplace set).