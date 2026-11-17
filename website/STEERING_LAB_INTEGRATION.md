> Historical integration plan. The multi-layer Explore implementation now ships;
> see [website README](README.md) for the current controls and API contract.

# Steering Lab integration

## 1. Design and regression check — implemented

The lab evolves the Stitch exports into a three-column desktop workspace: model
and layers on the left, output above draft/alpha in the center, and an inspector
on the right. Keep the shared navigation and individual page routes. The live draft, alpha slider, streaming,
cancellation, result cache, original-input highlights, copy, and retry use the
existing lifecycle. The model diagram shows the current configuration, not live
activation measurements. Scores are empty; feedback is disabled. The read-only
system prompt comes from `BASE_REWRITE_PROMPT`, not a second copy in the template.
The inspector already exposes actual completed-run metadata and source/output
word differences. These do not require an evaluation service and are not quality
or activation measurements. Evaluation remains a separate integration phase.

The diagram uses **decoder indices 0–23**. The current index 11 is the twelfth
decoder block. Pooling describes extraction of the direction; inference currently
adds that direction to every token representation at the selected block output.
No inference code, request schema, vector artifact, or scheduling behavior changes
in this phase.

## 2. Describe supported experiments

Add a versioned model/vector manifest and expose it through the configuration API.
For each supported combination record model ID and revision, decoder index,
extraction pooling (`mean` or `last_token`), artifact path under `artifacts/`,
candidate key, direction sign, normalization, and recommended tested alpha range.
Check vector dimensions and layer bounds when loading. Keep the notebook's
hidden-state-to-decoder indexing convention explicit and verified against the
finalized run. Do not label unverified layers as optimal or supported.

Inventory the saved candidates first. Extract missing layer/pooling combinations
with the finalized research notebooks, verify them, and promote the results into
`artifacts/`. A vector extracted at one layer must not silently become the vector
for every layer. The frontend should enable only combinations listed as available.
Keep the existing index-11 mean-pooled candidate as the default.

Acceptance: configuration accurately describes every enabled option; unavailable
combinations cannot reach generation; default outputs match the current baseline.

## 3. Connect layer, pooling, and prompt controls

Extend the validated request with model ID, decoder index, pooling, and system
prompt/preset identity. Start with the current Qwen model rather than loading
several models during slider movement. Resolve each request through the manifest.
Represent each admitted job with an immutable settings snapshot; do not mutate
shared model settings when a UI control changes. Preserve serialized hook contexts,
cleanup, cancellation, input limits, and generation timeouts.

Add a bounded custom prompt and explicit no-system-prompt mode. Count the complete
chat prompt against the token limit. Changing any control creates a new revision,
just like changing alpha. Include **all settings**, source text, generation policy,
and manifest version in cache keys and completed response metadata. Distinguish
requested settings from those used for the displayed result throughout streaming.

Acceptance: each enabled control changes the actual request and correct hook;
invalid combinations are rejected; rapid mixed control changes never display an
obsolete result. Test simultaneous sessions for hook/settings isolation. Compare
the default path with the finalized notebook and existing integration verifier.

## 4. Evaluate completed responses

Define and version the scorers before adding numbers to the chart. Show separate
formality, entailment, and embedding-similarity measurements with their definitions
and limitations. None should be labeled a guarantee of preserved meaning.

Run evaluation after a completed rewrite, off the generation path. Tie each result
to its request ID, input revision, settings, source/output pair, and scorer version.
Cancel or ignore obsolete evaluations. Evaluation errors must not remove a valid
rewrite or block slider interaction. Label loading, failed, and unavailable scores.

Plot only measured points for the same source, prompt, model, layer, pooling, and
scorer versions. Reset the series when those change. Do not synthesize scores from
alpha or interpolate unmeasured runs as if they were observations. Compare against
an explicit alpha-zero run with otherwise identical settings.

Acceptance: delayed scores never attach to a newer rewrite; chart points are
traceable to completed runs; scoring does not slow down response streaming.

## 5. Feedback and release check

Decide storage, consent, and deletion behavior before enabling Save Pair. Persist
only deliberately submitted source/output pairs and their exact run configuration,
scorer versions, and user labels. Keep automatic drafting separate from collection.

Run the existing API/lifecycle/browser checks plus real-model comparisons across
supported layer/pooling settings. Review desktop and mobile layouts, keyboard
controls, prompt limits, rapid changes, cancellation, retry, and unavailable models.
Keep each integration phase reviewable independently so regression causes remain
easy to identify.
