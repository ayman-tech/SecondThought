# Steering integration review — 22 November 2026

The control-to-artifact wiring is correct for all **336 selectable vectors**:
seven features × 24 decoder blocks × mean/final-token pooling. All seven features
can be enabled independently or composed. Five additional legacy reference vectors
remain compatibility defaults and are intentionally excluded from frontend selection.

This review separates numerical correctness, integration, and behavioral validity.
Passing the first two does not establish the third. Existing vectors, scores,
normalization choices, defaults and artifact bytes were not replaced in this review.

The [machine-readable audit](../research/steering_experimentation/artifacts/lab_v1/feature_integration_audit.json)
records all vector measurements, source-audit results, numerical reproduction
status and integration check totals, bound to the reviewed catalog fingerprint.

## What was checked

- Every frontend feature/pooling/layer choice has exactly one available catalog
  vector and an associated held-out measurement for that same vector ID.
- All 336 actual frontend request payloads were submitted to the real backend
  resolver. Feature, layer, pooling, strength, artifact and candidate identities
  matched. Positive and negative strengths were exercised. Completion text was
  stubbed for this exhaustive routing check, not generated 336 times.
- Actual rendered layer fills matched the colour mapping for all 336 choices,
  including after switching feature and pooling. No substitute legacy score is
  used for a newer vector. Selected-layer outlines remain purple; their fill still
  represents held-out ordering. Colour is for the **edited feature and pooling**,
  not a blended score for every enabled feature.
- Available source split fingerprints matched extraction provenance. Recomputing
  all raw means and all held-out ordering counts reproduced **48/48 candidates
  for each of six features**, with maximum absolute vector error **0** on the
  recorded float32 MPS environment: detoxification, fluency, simplification,
  conciseness, empathy and politeness. No source sentences are in the audit report.
- The restricted GYAFC corpus is not present locally. Formality's artifact checks,
  runtime scale, frontend routes and colours were verified; its raw-data means
  and held-out counts were **not independently reproduced**.
- Hook checks cover all 341 catalog vectors, exact additions at declared decoder
  block outputs, prefill/decode execution and cleanup. Signed seven-feature
  composition checks cover both shared and independent layers.

## Feature-by-feature findings

| Feature | Data and held-out evidence | Extraction/behavioral issues | Wiring |
| --- | --- | --- | --- |
| Formality | GYAFC, 8,000/2,000 pairs. Mean ordering 49.90–95.95%; final token 70.20–94.45%. | Mean layers 3–16 have pair-level 95% intervals containing 50%. Several additional mean layers remain close to chance. Raw source/target leakage could not be audited without the restricted corpus. The loader deduplicates sources, not connected source/target variants. | All 48 selectable vectors resolve correctly. Raw runtime scale is intentional and differs from the other six features. |
| Detoxification | ParaDetox, 8,000/2,000. Mean 86.00–99.65%; final token 86.50–98.10%. Means and counts reproduced exactly. | Three normalized neutral strings occur in both extraction and held-out data, affecting 3/2,000 held-out pairs (0.15%). Sources are disjoint, but this is not full source/target isolation. Targets average about 78% of source word count, so deletion/length is a possible confound. Separation is not measured toxicity reduction in generated text. | All 48 resolve correctly; unit-L2 scaling and positive neutral-minus-toxic orientation verified. |
| Fluency | IteraTeR-HUMAN, 542/84. Mean 58.33–80.95%; final token 58.33–79.76%. Means and counts reproduced exactly. | Human labels identify edit intent, not guaranteed improvement. Formatting, punctuation and occasional worse revisions are included. Only 84 held-out pairs from 20 documents; mean L23 and final-token L1 intervals include chance. Response fluency/meaning preservation has not been established. | All 48 resolve correctly; no feature/pooling crossover found. |
| Simplification | WikiLarge train, 2,000/500. Mean 70.20–81.00%; final token 69.60–82.60%. Means and counts reproduced exactly. | 659/2,500 selected pairs match serialized-bracket or encoding markers (`-LRB-`, `-RRB-`, replacement characters or `â`). These matches require normalization review; they are not all proven corrupt examples. Automatic alignment can add/remove facts or change entities. Average target/source word ratio is 0.895. No article IDs are available, so sentence-component isolation is not article isolation. | All 48 resolve correctly; displayed scores belong to the selected simplification artifact. |
| Conciseness | Google compression train01, 2,000/500. Mean 98.20–100%; final token 91.80–100%. Means and counts reproduced exactly. | Targets average 56% of source word count. This can primarily measure shortening rather than preserving essential information. Compression can remove important context. The corpus is news-domain, not general writing. | All 48 resolve correctly; source document groups and connected text variants are split apart. |
| Empathy | EPITOME emotional-reaction ablation, 417/105. Mean 93.33–100%; final token 86.67–92.38%. Means and counts reproduced exactly. | Not human-rated low/high response pairs: annotated spans are removed mechanically. Targets average 1.425× source word count; span presence and length are major confounds. Removing spans can hurt grammar. The support-seeking context controls the split but is not encoded in the raw-text response representations. This supports a narrow emotional-acknowledgment experiment, not broad context-sensitive empathy. | All 48 resolve correctly. Derived construction is disclosed under Dataset & direction; source attribution is retained. |
| Politeness | Automatically labeled high-scoring email requests, 2,000/500. Mean 94.80–100%; final token 97.20–99.80%. Means and counts reproduced exactly. | Contrasts delete standalone `please`; these are not human-rated matched politeness judgments. High ordering can mostly reflect detecting that token. Courtesy, deference, tact and respectful disagreement are not comprehensively represented. No message/thread IDs are provided in the training-ready archive. | All 48 resolve correctly. Feature/pooling evidence and exact marker-ablation artifact identities match. |

## Cross-feature limitations

1. **Held-out ordering is not steering effectiveness.** It tests whether the target
   activation projects farther along the learned direction. It does not measure
   whether adding that direction improves a generated response. High separation
   can arise from token presence, length or formatting. Negative alpha is not a
   validated inverse behavior.
2. **Strengths are not calibrated.** Formality uses raw scale; other features use
   unit-L2 scale. Raw direction norms vary substantially by layer and feature.
   Equal slider values do not imply equal residual perturbations or behavioral
   effects. No aggregate norm budget limits multiple features/layers; combinations
   can interfere or collapse generation even when each hook is correct.
3. **Extraction and serving contexts differ.** Extraction uses raw text without a
   chat template; inference uses task instructions and sometimes assistant prefill.
   Hooks add shifts to every token during prompt processing and generation. No
   separate validation establishes transfer to Continue, Answer, Summarize or
   Rewrite & continue. The latter applies the same plan in both stages.
4. **Pooling has confounds.** Mean pooling can encode length and common token
   distribution. Final-token pooling can encode punctuation/end-of-sentence
   differences. Neither isolates a feature from topic or unrelated style.
5. **Uncertainty is limited.** Wilson intervals are pair-level and do not fully
   account for shared documents or contexts. Scores should be compared within one
   feature/pooling/source cohort, not used to rank different features' quality.
6. **Historical provenance is incomplete.** Existing artifacts do not record batch
   size as a dedicated field. Reproduction used documented release recipes (16
   pairs for detoxification; 8 for fluency and newer features). The five legacy
   reference snapshots also lack established extraction revision/precision. Future
   extraction reports now record batch size and estimator name explicitly.

## Integration fixes made during review

- A disabled/unselected spider-axis keyboard release could flush pending input
  even though that axis could not change its vector. It now uses the same enabled,
  selected and available guards as pointer/slider controls. A regression check
  covers this case.
- Precise slider step sizes were hardcoded to 0.1. They now follow the selected
  vector's declared `strength_step`. All current vectors use 0.1, so this repairs
  future catalog compatibility without changing current values.
- Browser verification now checks every real control-generated payload against
  backend resolution and checks computed fill colours, rather than relying only
  on DOM score/ID attributes.
- Added a read-only audit command that verifies exact evidence identities, runtime
  normalization, split fingerprints, cross-side text overlap and optional
  numerical reproduction. Missing source corpora are explicitly reported.

## Recommended next release work

Keep these vectors versioned while investigating data quality; do not silently
relabel or replace their scores. For a reviewed successor release:

- Split GYAFC/ParaDetox using connected source/target groups and audit near duplicates.
- Normalize and review WikiLarge formatting/alignment examples before extraction.
- Curate improvement-rated fluency pairs; use stronger independent evaluation.
- Add content/length controls and human review to empathy and politeness contrasts.
- Evaluate each feature causally on unseen prompts at zero, positive and negative
  strengths before recommending layers or ranges. Measure meaning, task compliance
  and degeneration alongside the intended feature. Calibrate combinations separately.

These data/model limitations remain open. The review confirms integration, not
general behavioral reliability.

## Reproduce the checks

```bash
uv run --locked python -m research.steering_experimentation.audit_lab_features \
  --recompute --device mps --output /tmp/secondthought-feature-audit.json
# Add --gyafc /path/to/GYAFC_Corpus for the restricted formality source audit.
uv run --locked python -m research.steering_experimentation.verify_lab_catalog \
  --device mps --output /tmp/secondthought-review-hooks.json
uv run --locked python -m website.api.server
# Separate terminal:
node website/frontend/tests/browser-smoke.mjs
```

Reproduction requires the cached pinned model and the original ignored prepared
datasets. Audit outputs are read-only reports; they never promote regenerated
vectors. The browser suite writes `vector-routing.json` with every selected ID,
score and backend-resolved artifact fingerprint. Unit suites cover catalog,
pooling, isolation, invalid settings, composition, request lifecycle and controls.
