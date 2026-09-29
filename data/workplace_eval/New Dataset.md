# GYAFC — Grammarly's Yahoo Answers Formality Corpus

**The corpus is not in this repository and cannot be added to it.** This file documents what it is, how SecondThought uses it, and how to obtain your own copy.

> Rao, S. and Tetreault, J. (2018). *Dear Sir or Madam, May I Introduce the GYAFC Dataset: Corpus, Benchmarks and Metrics for Formality Style Transfer.* NAACL-HLT 2018. [arXiv:1803.06535](https://arxiv.org/abs/1803.06535)

---

## 1. Why this dataset cannot go in the repository

**It is access-controlled and not ours to redistribute.** GYAFC is not publicly downloadable. Access is granted individually: each person must email the corpus maintainers at `gyafc.dataset@gmail.com` with their affiliation and a description of their intended use, and receives the data directly from them under the terms they specify.

That single fact settles it. Committing the corpus here would:

- **Circumvent the maintainers' access control.** The gate exists so the authors know who holds the data and for what purpose. A public repo — or a private one shared with anyone who hasn't been granted access — routes around that entirely.
- **Redistribute data we have no right to redistribute.** Our grant covers our use, not onward distribution. Passing it to a third party is not ours to do, regardless of how narrow the audience is.
- **Be irreversible.** Git retains every version. Once committed, the data is in the history permanently; `git rm` does not remove it, and a repo that is private today may not be private later.

**The practical consequence for the team:** every collaborator requests their own copy. This is a few days of turnaround, so request early. Nobody should be sent the files directly, including over Slack, email or a shared Drive folder — the same restriction applies to us as to anyone else.

This sits alongside the project-wide rule in [`../README.md`](../README.md): no corpus of any kind is committed. GYAFC has the strongest reason, but the policy is uniform.

---

## 2. What the corpus contains

Sentence pairs from Yahoo Answers, each written in both an informal and a formal register, across two topical domains.

| Domain | Train | Tune (inf→for) | Test (inf→for) |
|---|---:|---:|---:|
| Entertainment & Music (E&M) | 52,595 | 2,877 | 1,416 |
| Family & Relationships (F&R) | 51,967 | 2,788 | 1,332 |

The corpus also covers the reverse direction (formal → informal): 2,356 tune / 1,082 test for E&M and 2,247 / 1,019 for F&R. **We do not use the reverse direction.**

**Tune and test sets carry four human-written references per sentence.** This is one of the corpus's most valuable properties — formality transfer can be scored against multiple valid rewrites rather than a single gold string, which is the right way to measure a task with many correct answers.

Expected local layout once you receive it:

```
data/gyafc/
  Entertainment_Music/
    train/            informal, formal
    tune/             informal, formal, formal.ref0 … ref3
    test/             informal, formal, formal.ref0 … ref3
  Family_Relationships/
    ... same structure
```

Everything above is gitignored. Only this README and the `.gitignore` are tracked.

---

## 3. How SecondThought uses it

GYAFC is **stage one of a three-stage curriculum**, and it carries the foundation the rest of the system builds on: it teaches the model what formal register *is*, so that later training can focus entirely on our specific task.

| Stage | Corpus | What it teaches |
|---|---|---|
| 1 | **GYAFC** | Register transfer: informal → formal English |
| 2 | ParaDetox | Removing hostility and profanity |
| 3 | Workplace corpus (distilled, ours) | The real task: preserve facts, actions, criticism and polarity |

**Why this order.** Our workplace corpus is the expensive one — a few thousand distilled pairs. Pre-training on roughly 100k GYAFC pairs means the model arrives at stage 3 already fluent in how formal English is constructed, so the whole of that small, costly corpus is spent on what only it can teach. GYAFC is what makes the three-stage approach affordable.

**Concretely:**

- **Intermediate fine-tuning.** `flan-t5-base` and the `Qwen2.5-1.5B` LoRA  are trained on GYAFC informal→formal before the workplace corpus. Both domains are combined; there's no reason to restrict to one.
- **F&R is especially valuable.** Family & Relationships contains interpersonal conflict, grievance and blame — structurally close to our input. We combine both domains for volume and report ablations separately, since establishing how much F&R contributes on its own is a result worth having.
- **Formality classifier calibration.** The pass-through gate (§3.3 of the proposal) needs to decide whether an input is *already* professional. GYAFC's paired informal/formal sentences are exactly the labelled data that threshold should be calibrated against.
- **External benchmark.** The GYAFC test set with its four references is a standard, comparable measurement of the formality-transfer component. Our own workplace test set measures the product; GYAFC measures one capability the product depends on, against published numbers.

---

## 4. Why this corpus is a strong fit

- **Scale where we need it most.** Over 100,000 paired sentences across both domains — roughly twenty times the size of our workplace corpus. Register is the one capability we can learn from abundant public data, and GYAFC supplies it at a volume we could never afford to distil ourselves.
- **Genuinely parallel.** Each sentence exists in both registers, written by people. This is a direct supervised signal for exactly the transformation our product performs, which is rare: most style-transfer work has to make do with non-parallel corpora and weaker training objectives.
- **Human-written formal targets.** The formal side was produced by trained annotators, so the model learns register from natural professional English rather than from another model's output.
- **Multi-reference evaluation.** Four human rewrites per tune and test sentence let us score against the full range of valid answers, and let us report numbers directly comparable to published results on the same benchmark.
- **Interpersonal subject matter.** The Family & Relationships domain covers disagreement, grievance and blame between people — the same conversational territory our product operates in, which makes the transfer to workplace messages a short one.
- **An established benchmark.** GYAFC is the standard corpus for formality style transfer, so building on it places our work in a recognised line of research and makes our results legible to anyone who knows the field.

---

## 5. Citation

Any report or paper using this corpus should cite:

```bibtex
@inproceedings{rao-tetreault-2018-dear,
  title     = {{GYAFC} Dataset:
               Corpus, Benchmarks and Metrics for Formality Style Transfer},
  author    = {Rao, Sudha and Tetreault, Joel},
  booktitle = {Proceedings of NAACL-HLT},
  year      = {2018}
}
```
}
```
