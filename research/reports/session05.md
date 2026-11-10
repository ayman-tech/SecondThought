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

# SecondThought: Weekly Report

## Shipped this week

- Evaluation pipeline with three measures: toxicity (Detoxify), semantic similarity (all-mpnet-base-v2), and critical-value preservation (local extractor). In review (PR #15).
- Critical-value extractor handles numbers, dates, times, money, percentages, units, emails, URLs, mentions, ticket IDs. Normalises safe formatting differences such as `2 files` / `two files` and `$1,000` / `$1000`. Matching is type-aware and duplicate-aware (PR #15).
- Extractor also reports values found in the output but absent from the input, which catches invented or altered deadlines and quantities. A changed date shows as one missing value and one unsupported value (PR #15).
- Evaluator accepts a `critical_values` column so human annotations can define required values where regex cannot infer them, such as person, client and project names (PR #15).
- `secondthought evaluate` CLI writes a per-example CSV plus dataset aggregates. Evaluator models load once per command and records process in batches (PR #15).
- Documented limitations of each evaluator so thresholds get chosen on labelled data instead of assumed (PR #15).
- SecondThought MVP built, giving the project its first working rewrite path (PR #3).
- `t5-small` fine-tuned on ParaDetox. Train, validation and test splits built so repeated inputs cannot leak across them. Five epochs completed, epoch 3 selected on validation loss (PR #4).
- Colab training set up with checkpoint selection, evaluation, model export and ZIP download (PR #4).
- Local inference notebook runs the exported model on CPU. No GPU or API key needed (PR #6).
- Dependencies moved into `pyproject.toml`, CPU environment configured with `uv`, merge conflicts resolved without disturbing the OpenAI baseline (PR #4, #6).
- 35 toxic workplace messages written for evaluation, carrying numbers, quantities, deadlines, names and addresses. They yield 45 extractable critical values (PR #6).
- Batch inference script ran the epoch-3 checkpoint across all 35 messages, producing a CSV with rewrites, latency, token counts, model metadata and metrics (PR #6).
- 20 automated tests added. All pass (PR #6).
- Chrome extension plus local API server, the project's first user-facing surface. The extension posts to the server, so the API key stays out of the browser and the model can be swapped without touching the extension (PR #5).
- Server shares its rewriter, config and prompt with the CLI and Gradio app, so all three surfaces behave the same way (PR #5).
- `/health` endpoint wired to a status indicator in the popup. Typed error responses covering blank input, malformed body, failed model call and missing key. CORS limited to extension origins (PR #5).
- Selected text on a page is pulled into the popup automatically, so a draft in Gmail or Slack can be rewritten without copying (PR #5).
- Manual acceptance protocol covering four cases: hostile message, urgent message with a deadline, already-professional message, and server unreachable (PR #5).
- Extension README written with setup steps, the health check, and the manual test script (PR #5).
- GYAFC corpus access requested and granted. Access is per-person by maintainer approval and the corpus is not publicly downloadable (PR #12).
- GYAFC adds about 105,000 parallel informal/formal sentence pairs: 52,595 training sentences in Entertainment & Music and 51,967 in Family & Relationships. Tune and test sets carry four human references per sentence (PR #12).
- GYAFC will serve as stage one of a three-stage curriculum (GYAFC, then ParaDetox, then our distilled workplace corpus), so the small workplace corpus is spent only on what it alone can teach (PR #12).
- Data card written covering corpus contents, licensing position and why the files cannot be committed (PR #12).
- Repository scaffolding added so the corpus stays private while the work stays reproducible: deny-by-default `.gitignore`, JSON Schema for the pair format, synthetic sample records, preparation script with content-hash splitting, checksum manifest for citing exact corpus versions (PR #12).

## User / validation learning

- No sessions with real users have been run yet, so there is no user-derived learning this week.
- The evaluation caught a failure a single metric would have hidden. Critical-value recall was perfect and mean output toxicity was 0.056, which looks like success. The edit ratio of 0.064 shows the model is substituting single words, four messages came back untouched, and three lost a sentence. Reading the measures together is what exposed this.
- Writing the 35-message set showed how much of a real complaint is load-bearing detail. Deadlines, quantities, names and addresses all have to survive for the message to still do its job.
- Planned for next week: 5 task-based trials using the acceptance protocol as the script. Show a participant the original and our rewrite, then ask whether they would send it to their own manager as-is. That question tests whether the output is sendable.

## Metrics snapshot

In-house `t5-small`, epoch-3 checkpoint, all 35 workplace messages. First full measurement, no prior week to compare.

- Critical-value recall (micro, 45 values across 26 messages): 1.000. Nothing missing, nothing invented.
- Critical-value exact-success rate: 35/35.
- Mean toxicity, input to output: 0.604 to 0.056.
- Mean relative toxicity reduction: 83.9%.
- Mean semantic similarity: 0.967 (minimum 0.784).
- Mean latency: 153 ms (range 101 to 216 ms).
- Exact-copy rate: 4/35.
- Mean edit ratio: 0.064.
- Mean word overlap: 0.883.
- Mean length ratio: 0.905 (minimum 0.429).
- Automated tests: 20/20 passing.

GPT-4.1-mini baseline, 10 messages, legacy metrics only: 10/10 completion, number recall 1.00, word overlap 0.59, edit ratio 0.26, mean latency about 1.3 s.

What the numbers say when read together:

- Fact preservation is perfect. All 45 critical values survived and nothing was invented. No altered deadlines, order numbers, addresses or amounts.
- Toxicity fell sharply, by 83.9% in relative terms.
- The edit ratio of 0.064 and word overlap of 0.883 show the model is doing word-level substitution instead of rewriting. "I'm sick of your bullshit excuses, Daniel" becomes "I'm sick of your excuses Daniel". The profanity is gone and the message is still not sendable to a manager. The high semantic similarity partly reflects how little changed.
- At 153 ms the local model is about 8 times faster than the API baseline and sits well inside the 1.5 s budget a messaging flow needs.

The checkpoint is safe on facts and fast, and it is not yet doing the task. That is the expected outcome for a model trained on ParaDetox instead of workplace data.

## Challenges / blockers

- The model substitutes words instead of rewriting. Closing that gap needs workplace training data, not more ParaDetox epochs.
- Four messages returned byte-identical. Two still scored 0.495 and 0.473 on toxicity, so the model declined to act on hostile input. Nothing currently blocks these from reaching a user.
- Three messages lost content. `input_032` came back at 43% of its original length, `input_035` at 64%, `input_022` at 70%. In each case the hostile clause was deleted instead of rephrased. Critical-value recall does not catch this; length ratio and semantic similarity do.
- Two substitutions damaged meaning. "a complete shitshow" became "a complete show". "out of your ass" became "out of your mind". No current measure flags either.
- The GPT baseline has only been scored on 10 messages with legacy metrics. Running it through `secondthought evaluate` on the same 35 messages is cheap and is the next step that unblocks comparison.
- No calibrated toxicity threshold. Detoxify was trained on internet comments and may over-score quoted profanity while missing workplace condescension. Our own results show the gap: mean residual toxicity of 0.056 looks fine, yet several outputs remain unsendable. Setting a threshold needs human-labelled workplace examples we do not have.
- Critical-value recall is flattered by empty cases. Nine of the 35 messages contain no extractable values and score 1.0 by default. The honest figure is micro-recall over the 45 real values, which is what we report.
- The frozen benchmark needs human annotation. Automatic extraction cannot infer person, client or project names. The evaluator accepts a `critical_values` column for these and the work has not started.
- Two failure modes no measure catches: reversed relationships between preserved values (who owes what to whom), and whether a requested action was paraphrased correctly. Both need human review.
- 35 messages is enough for diagnosis and too few to separate systems with confidence. Target is 100 to 200.
- Each collaborator needs their own GYAFC grant. We cannot forward the files. Turnaround is a few days, so requests should go out now.
- The extension only runs locally. The server address is hardcoded to `127.0.0.1:8000` and nothing is hosted, so a participant cannot use it without cloning the repo and supplying an API key. This blocks user trials until we either host the server or run sessions on our own hardware.
- Help needed: a reviewer for PR #15, and two people to run the user trials.

## Next week's goal

- Run the GPT baseline through `secondthought evaluate` on the same 35 messages and produce one comparison table.
- Add a no-op guard so an output identical to a toxic input fails instead of passing silently.
- Annotate the 35-message set with human `critical_values` and grow it past 100 as the frozen benchmark.
- Label a small set of workplace examples for toxicity so a threshold can be calibrated.
- Generate the first batch of distilled workplace training pairs, including already-professional messages that must come back unchanged.
- Run 5 user trials through the Chrome extension.

## Individual contributions

- ayman-tech (Owner): `t5-small` fine-tuning notebook on ParaDetox with leakage-safe splits; Colab training with checkpoint selection, evaluation, export and ZIP download; completed the 5-epoch run and selected epoch 3; local CPU inference notebook; 35-message workplace evaluation set; epoch-3 batch inference script producing the metrics CSV; 20 automated tests; dependencies migrated to `pyproject.toml` with a `uv` CPU environment; merge conflicts resolved without disturbing the OpenAI baseline (PR #4, #6, #2, #1).
- princeixr: SecondThought MVP, giving the project its first working rewrite path; evaluation pipeline covering Detoxify toxicity scoring on input and output, all-mpnet-base-v2 semantic similarity, and the local type-aware critical-value extractor with normalisation, duplicate awareness and unsupported-value detection; support for human `critical_values` annotations; `secondthought evaluate` CLI writing per-example CSV and dataset aggregates with batched processing; documented limitations of each evaluator so thresholds get chosen on labelled evidence (PR #3, #15).
- SAI-RAHUL-M: Chrome extension and local API server, the project's first user-facing surface; architecture keeping the API key server-side and sharing one rewriter, config and prompt across extension, CLI and Gradio so all three behave identically; `/health` endpoint with a live status indicator in the popup; typed error responses for blank input, malformed body, failed model call and missing key; CORS limited to extension origins; automatic pickup of selected page text; four-case manual acceptance protocol; extension README with setup steps and test script (PR #5).
- moziyadh110: GYAFC corpus access request and approval, clearing a per-person maintainer gate; data card covering the corpus, its place in the three-stage curriculum and the licensing position; repository scaffolding keeping the corpus private while the work stays reproducible, including deny-by-default `.gitignore`, JSON Schema for the pair format, synthetic sample records so the pipeline runs without the real data, preparation script with content-hash splitting that makes cross-split leakage structurally impossible, and a checksum manifest for citing exact corpus versions (PR #12).

## Lean canvas changes

- Problem, sharpened. Existing tools soften a message until the complaint disappears. Keeping the criticism, the figures and the requested action is the product. Our evaluation now measures that directly, so the measure and the promise are the same thing.
- Value proposition moved from "sound professional" to "say the same thing, safely". Critical-value recall is how we prove it.
- Cost structure. A quantised small model on-device would cut inference cost to near zero and remove the objection that the tool sends everything you type to a server. That makes the small-model path a commercial decision as much as a technical one.
- Risk. The largest open risk is repeat usage. Users may rewrite one message, feel relief, and never return. Testing this is cheap and should happen before further model investment.
