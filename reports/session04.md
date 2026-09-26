---
team: SecondThought
session: "04"
date: 2026-09-22
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

## Shipped this week

- Built the first locally runnable SecondThought MVP: a user enters a difficult workplace message and receives a professional rewrite from an OpenAI model.
- Created a configurable OpenAI Responses API baseline using external model, output-length, and constrained-prompt settings to evaluate professional rewriting while preserving critical message details.
- Added a 10-message JSONL sample dataset containing production-like records with only an ID and original text. Demo inputs are not hard-coded in Python.
- Added a basic evaluation pipeline that appends number recall, word overlap, edit ratio, length ratio, and exact-match columns.
- Added setup, execution, configuration, and evaluation instructions to the README.



## User evidence

- The development is still in progress, hence we haven't deployed it yet.



## Metrics snapshot

The constrained OpenAI baseline was run on all 10 records in `data/workplace_eval/sample.jsonl`. The evaluated result is stored locally in `outputs/constrained_evaluated.csv`.


| Metric                | Result      |
| --------------------- | ----------- |
| Completed generations | 10/10       |
| Average latency       | 1,284.77 ms |
| Average number recall | 1.0000      |
| Average word overlap  | 0.5925      |
| Average edit ratio    | 0.2561      |
| Average length ratio  | 1.0473      |


- **Measured on:** the 10-example development sample, not a held-out test set.
- **Model:** `gpt-4.1-mini-2025-04-14` using the constrained prompt in `prompts/constrained.txt`.
- **Same model as the running product:** yes. The CLI batch and Gradio application use the same configuration and rewriter implementation.
- **North-star metric:** not yet measured. The current automatic metrics describe how much text changed and whether digits were retained; they do not establish whether a rewrite is sendable or whether intent was preserved.



## What did not work

- The current evaluation is too shallow to validate the central product claim. Number recall, word overlap, edit ratio, length ratio, and exact match do not directly measure professionalism, semantic preservation, urgency, criticism, or requested-action preservation.
- The product has only been run locally and has not yet been tested by a qualifying external user.



## Challenges / blockers

- “Intent preservation” is difficult to measure automatically from only the original and rewritten text. Deterministic checks can detect missing digits, but urgency, criticism, accountability, and requested actions require stronger evaluators and eventual human validation.



## Next week's goal

1. Refine the problem statement around a clearly defined target user group and use case.
2. Develop an initial prototype of our own paraphrasing model.
3. Design meaningful metrics for evaluating rewrite quality and intent preservation.



## Lean canvas changes (if any)

- **Value proposition:** SecondThought should be evaluated on preservation and usefulness, not merely on whether the output sounds nicer.
- **Primary risk:** an existing general-purpose LLM may already perform the rewrite well enough. The cheapest next test is a direct comparison of naive and constrained prompting with real users, before fine-tuning a custom model.

