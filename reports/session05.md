---
team: SecondThought
session: "05"
date: 2026-09-29
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

# SecondThought — Weekly Report

## Shipped this week

- **Three-axis evaluation pipeline** — in review (evidence: PR #15). Replaces surface-level string metrics with three complementary measures, each answering a question the others cannot: **toxicity reduction** (Detoxify, scoring input and output so the change is measurable), **semantic similarity** (`all-mpnet-base-v2` cosine similarity as an intent-preservation proxy), and **critical-value preservation** — a local, type-aware extractor for the facts that must not change: numbers, dates, times, money, percentages, durations, units, emails, URLs, mentions, ticket IDs and acronyms. It normalizes safe formatting differences (`2 files` ↔ `two files`, `$1,000` ↔ `$1000`, `5 PM` ↔ `5 p.m.`), is duplicate- and type-aware, and separately reports values appearing in the output but *not* the input — exposing invented or altered deadlines and quantities. Exposed as `secondthought evaluate`, writing a per-example CSV plus dataset-level aggregates.

- **In-house model trained end to end** (evidence: PR #4, #6). A `t5-small` fine-tuning notebook on Hugging Face's ParaDetox, with train/validation/test splits built to prevent repeated-input leakage. Colab training configured with checkpoint selection by validation loss, evaluation, model export and ZIP download. The **5-epoch run completed, with epoch 3 best on validation loss** — so we have a selected checkpoint, not just a training script. A separate local inference notebook accepts typed sentences and returns detoxified rewrites on CPU, no GPU or API key required. Supporting work: dependencies moved into `pyproject.toml`, a CPU environment configured with `uv`, and merge conflicts resolved while preserving the existing OpenAI baseline intact.

- **First workplace evaluation set and batch inference run** (evidence: PR #6). **35 realistic toxic workplace messages** authored deliberately to carry the details our product must not lose — numbers, quantities, deadlines, fictional names and addresses. A batch inference script runs the epoch-3 checkpoint across the set and produces a CSV with rewrites, per-example latency, token counts, model metadata and five comparison metrics. **20 automated tests added, all passing.** This is the first time the in-house model has been measured on workplace-shaped input rather than social-media text.

- **Chrome extension + local API server** — our first user-facing surface (evidence: PR #5). The extension posts to a local server rather than calling the model directly, so the API key never reaches the browser and the model can be swapped without touching the extension. The server shares its rewriter, config and prompt with the CLI and Gradio app, so all three surfaces behave identically. Includes a `/health` endpoint surfaced as a status dot in the popup, typed error responses, and CORS restricted to extension origins. Shipped with a **manual acceptance protocol**: three fixed cases covering the product contract — a hostile message (insult removed, figures and request preserved, still firm), an urgent message with a deadline (softened but still urgent, deadline intact), and an already-professional message (returned unchanged) — plus a server-down case confirming the failure path shows an error rather than hanging.

- **GYAFC corpus access secured, documented and scaffolded** (evidence: PR #12). GYAFC is not publicly downloadable — access is granted individually by the corpus maintainers on request, with affiliation and intended use stated — and that access is now in place. It adds roughly **105,000 parallel informal/formal sentence pairs** across two domains: Entertainment & Music (52,595 training sentences) and Family & Relationships (51,967), the latter covering interpersonal disagreement, grievance and blame, the closest public analogue to our own input. Tune and test sets carry **four human-written references per sentence**, giving multi-reference scoring and numbers comparable to published results on a recognised benchmark. Its role is **stage one of a three-stage curriculum** (GYAFC → ParaDetox → distilled workplace corpus): it teaches formal register from abundant public data so the small, expensive workplace corpus is spent entirely on what only it can teach. Shipped alongside: a data card covering usage and licensing, and repository scaffolding that keeps the corpus private while the work stays reproducible — a deny-by-default `.gitignore`, a JSON Schema for the pair format, synthetic sample records so the pipeline runs end to end without the real data, a preparation script with deterministic content-hash splitting that makes duplicate leakage structurally impossible, and a checksum manifest so any result can cite an exact corpus version without that corpus being public.

## User / validation learning

- **Our quality bar is now written down and machine-checkable.** The evaluation work (PR #15) encodes the product promise as measurable criteria; the extension's three-case protocol (PR #5) makes the same contract checkable by hand in under a minute. The insight shaping both: *no single metric answers the question*. A copied toxic input scores near-perfect semantic similarity; a polite but unrelated output scores near-zero toxicity. Only reading the three axes together separates a good rewrite from a fluent failure.
- **Authoring the 35-message set was itself a finding.** Writing realistic workplace messages made concrete how much of a real complaint is load-bearing detail — deadlines, quantities, named people, addresses. A rewrite that reads well but drops any of them has failed, and this set is built specifically to catch that.
- **No sessions with real users have been run yet**, so there is no user-derived learning to report. The extension is the surface that makes those sessions possible.
- **Planned for next week:** 5 task-based trials using the three-case protocol as the script — show a participant the original and our rewrite, ask whether they would send it as-is to their own manager. That measures the only thing that matters now: whether the output is *sendable*, not whether it is polite.

## Metrics snapshot

GPT-4.1-mini baseline, 10-message sample (first measurement, no prior week to compare):

- Generation completion: **10/10**
- Legacy number recall: **1.00**
- Word overlap: **0.59**
- Edit ratio: **0.26**
- Mean latency: **~1.3 s**

In-house `t5-small`, epoch-3 checkpoint: batch inference completed across all **35 workplace messages**, with rewrites, latency, token counts and five comparison metrics written to CSV. Automated test suite: **20/20 passing.** Aggregate figures to be reported once both systems are scored on the same set.

Both systems have now been measured, but on different samples and with the legacy metric set. Re-running both through `secondthought evaluate` on the 35-message set is what makes them comparable.

## Challenges / blockers

- **The two systems are measured but not yet comparable.** The GPT baseline was scored on 10 messages, the T5 checkpoint on 35, both with legacy metrics. One shared run through `secondthought evaluate` fixes this and is the single highest-value next step.
- **No calibrated toxicity threshold.** Detoxify returns raw scores and was trained on internet comments, not workplace communication — it may over-score quoted profanity and miss condescension, sarcasm or blame expressed in polite words. The pipeline deliberately declares no pass threshold; choosing one requires human-labeled workplace examples we do not yet have.
- **The frozen benchmark needs human annotation.** Automatic extraction cannot infer person names, client names or project names. The evaluator accepts a `critical_values` column for these, and the benchmark should carry annotations rather than rely on extraction alone. The 35-message set is the natural starting point, but annotating it is unstarted manual work.
- **Two failure modes no metric catches.** Critical-value preservation confirms *Alice*, *Bob* and *5 PM* all survive, but not that the relationship between them held — a rewrite could reverse who owes what to whom and score perfectly. Nor can it confirm a requested action was paraphrased correctly. Both need human review in the loop.
- **ParaDetox is a domain mismatch.** Social-media comments, not workplace messages. The model learns to soften text but drops details such as figures and requested actions. The 35-message set now lets us measure how badly; the fix is workplace training data.
- **Sample size.** 35 messages is enough for diagnosis, not enough to separate systems with confidence. Target is 100–200 reviewed workplace messages.
- **Each collaborator needs their own GYAFC grant.** Access is per-person by design and we cannot forward the files — the same restriction binds us as anyone else. Turnaround is a few days, so anyone touching stage-one training should request now rather than when they need it.
- **The extension only runs locally.** The server address is hardcoded to `127.0.0.1:8000` and nothing is hosted, so a participant cannot use SecondThought without cloning the repo and supplying an API key. This is the immediate blocker to user trials — either we run sessions on our own hardware, or we host the server.
- **Help needed:** a reviewer for PR #15, and two teammates to run the user trials.

## Next week's goal

- Merge PR #15 and run both the T5 epoch-3 checkpoint and the GPT baseline through `secondthought evaluate` on the same 35 messages — one comparison table, three axes, both systems
- Annotate the 35-message set with human `critical_values` and grow it toward 100+ as the frozen product benchmark
- Label a small set of workplace examples for toxicity so a threshold can be calibrated rather than guessed
- Generate the first batch of distilled workplace training pairs, including already-professional messages that must come back unchanged
- Run 5 user trials through the Chrome extension, on our own hardware or a hosted server

## Individual contributions

- **ayman-tech** (Owner): `t5-small` fine-tuning notebook on ParaDetox with leakage-safe splits; Colab training with validation-loss checkpoint selection, evaluation, export and ZIP download; completed the 5-epoch run and selected epoch 3; local CPU inference notebook; 35-message workplace evaluation set authored with embedded numbers, deadlines, names and addresses; epoch-3 batch inference script producing a metrics CSV; 20 automated tests, all passing; dependencies migrated to `pyproject.toml` with a `uv` CPU environment; merge conflicts resolved while preserving the OpenAI baseline (evidence: PR #4, #6, #2, #1)

- **princeixr**: SecondThought MVP; three-axis evaluation pipeline — Detoxify toxicity scoring on input and output, `all-mpnet-base-v2` semantic similarity, and the local type-aware critical-value extractor with normalization, duplicate awareness and unsupported-value detection; `secondthought evaluate` CLI writing per-example CSV and dataset aggregates; documented limitations of each evaluator so thresholds are chosen on evidence rather than assumed (evidence: PR #3, #15)

- **SAI-RAHUL-M**: Chrome extension and local API server; architecture keeping the API key server-side and sharing one rewriter, config and prompt across extension, CLI and Gradio so all three surfaces behave identically; `/health` endpoint with a live status indicator in the popup; typed error responses and CORS restricted to extension origins; three-case manual acceptance protocol plus a server-down failure-path check; extension README with setup and test instructions (evidence: PR #5)

- **moziyadh110**: GYAFC corpus access request and approval; data card covering the corpus, its role as stage one of the curriculum, and the licensing position; repository scaffolding that keeps the corpus private while the work stays reproducible — deny-by-default `.gitignore`, JSON Schema for the pair format, synthetic sample records, preparation script with deterministic content-hash splitting, and a checksum manifest for citing exact corpus versions (evidence: PR #12)

## Lean canvas changes (if any)

- **Problem, sharpened.** The problem is not "messages sound unprofessional" — it is that existing tools soften a message until the complaint disappears. Preserving the criticism, the figures and the requested action is the product, not a side constraint. Our evaluation now measures exactly that, so the metric and the product promise are the same thing.
- **Value proposition.** Shifted from *sound professional* to *say the same thing, safely*. Meaning preservation is what we are selling, and critical-value recall is how we prove it.
- **Cost structure.** A quantized small model running on-device would move inference cost close to zero and remove the "this tool sends everything I type to a server" objection, making the small-model path a commercial decision rather than only a technical one.
- **Risk.** The largest open risk is repeat usage: users may rewrite one message, feel relief, and never return. Cheap to test, and worth testing before further model investment.
