# Multi-feature runs

The v2 API accepts explicit vector interventions. Different features can target
independent decoder layers, share a layer, use different extraction pooling or
release versions, and have independent positive, negative or zero strengths.
There is no fixed list of feature names in the run resolver or compiler. A new
feature such as empathy requires a validated catalog entry and compatible
artifacts; it does not require another feature-specific generation branch.

The current production worker loads Qwen 2.5 0.5B only. Catalog support and a
loaded runtime are separate: registered but unloaded models return 503 for run
execution. Additional model architectures still require a compatible runtime
adapter; this release does not automatically load arbitrary models.

## Request

Read `GET /api/v2/lab/catalog`. Choose exact available vector IDs from it. The
identity includes the model, feature, layer, pooling, scale, extraction artifact
and candidate. Do not reconstruct an artifact path or pick the first result by
feature/layer when several extraction releases exist.

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "revision": 1,
  "model_id": "qwen2.5-0.5b-instruct",
  "input": "Send the report before noon.",
  "task": "rewrite",
  "interventions": [
    {"vector_id": "qwen-formality-l7-mean-v1", "strength": 0.4},
    {"vector_id": "qwen-detoxification-l7-mean-v1", "strength": 0.7},
    {"vector_id": "qwen-detoxification-l11-final_token-v1", "strength": -0.3}
  ],
  "generation": {"max_input_tokens": 2048, "max_new_tokens": 128}
}
```

Optional `catalog_version` pins the catalog digest returned by GET. A mismatch
returns 409 rather than silently resolving against a changed release. Exact
custom instructions use `task:"custom"` and `system_prompt`; presets and no-system
mode follow the same prompt contract as v1. Input whitespace is preserved in v2.
An empty `interventions` list is the prompted, unsteered baseline.

| Endpoint | Behaviour |
| --- | --- |
| `POST /api/v2/lab/runs/resolve` | Resolve metadata and identity without generating, enqueueing or consuming a revision |
| `POST /api/v2/lab/runs` | Return the completed run, with output in `text` |
| `POST /api/v2/lab/runs/stream` | NDJSON queued/started/delta/completed/cancelled/error events |
| `POST /api/v2/lab/runs/cancel` | Cancel a matching session/revision; cannot cancel a newer revision |

Resolution checks vector availability, model compatibility, duplicate IDs,
per-vector strength bounds and supported sites. Up to 256 interventions are
accepted. Nonfinite and boolean strengths, legacy alpha/beta fields, caller
supplied layer overrides and unknown fields are rejected. Even zero-strength
entries must reference available compatible vectors. Token-count/context-window
checks happen inside the model worker; metadata resolution alone does not
establish that a full prompt fits.

## Execution semantics

For every decoder output site, the compiler adds the weighted vectors:

```text
h_layer' = h_layer + sum(strength_i * effective_vector_i)
```

`effective_vector` uses that vector's catalog scale (`raw` or `unit_l2`). The
combined shift is not renormalized, averaged, clipped or orthogonalized. Thus a
strength is not automatically comparable across vector releases or features.
Cancellation between opposing directions is allowed; duplicate IDs must instead
be expressed as one combined strength.

All vectors at one layer are compiled into one shift and one hook. Separate
layers receive separate hooks. The current supported site is decoder block
output, applied to every token during input processing and generation. Extraction
pooling does not change token scope. The catalog validates architecture, revision,
shape, checksum and candidate metadata before tensor use. Compilation and model
generation run under the model lock; hooks are removed on success, failure,
cancellation or timeout. No request changes shared model generation defaults.

The execution plan is immutable. The worker resolves it again against its own
checked catalog before execution. Unsupported methods/sites require an explicit
adapter extension; no guessed fallback is used. Large or numerous interventions
can still degrade generation. Correct routing does not establish semantic
preservation or feature independence.

## Observability and compatibility

`resolve` returns a deterministic plan ID, full resolved interventions with
artifact checksums, exact instructions, generation budgets, input SHA-256 and an
experiment configuration ID. Session ID, revision and intervention input order
do not change this configuration identity. Changing input, prompt, strengths,
budgets or artifact/catalog identity does. These are configuration identities,
not a guarantee of bit-identical outputs across hardware or software versions.

Streaming events carry plan/experiment IDs. Completed events include the full
`applied` configuration, output, finish reason, token count, latency, runtime model
repository and serving version. Token deltas omit the full plan to keep streams
small. The input text itself is not copied into this metadata. Runs are not yet
persisted to a database; clients can save the completed configuration for records.

The production worker adapts existing v1 requests to the same canonical executor.
The frontend now sends v2 runs. Feature checkboxes enable independent banks;
**Edit layers for** chooses the bank shown in the diagram. Each bank retains its
own single/multi-layer mode, pooling, layer selections and strengths. The square
mixer on the diagram's left exposes a slider and a draggable radial point for
each feature's displayed layer. Feature angles are schematic and do not imply
measured vector similarity. Additional registered features generate controls
from the same catalog data. The wheel's white marker is a visual summary, not an
activation measurement. The per-feature sliders provide keyboard equivalents.

Disabling a feature removes its interventions and retains its settings for
re-enabling. Clear layers clears all banks; Reset restores only Formality at
layer 11/+0.5 with mean pooling. Active chips include feature, layer and strength.
Coloured dots beneath layers show interventions for all enabled features; the
score colours and focused outline describe the bank currently being edited.
The request cache keys include all exact vector/strength pairs, instructions,
model and budgets. Pointer release flushes pending work without duplicating
requests, including when dragging feature points.

For a future feature release, add its feature definition, checked artifact,
vector specifications and extraction provenance to the catalog. Use new vector
and artifact IDs for a changed extraction. The same v2 request/executor then
supports it. The synthetic empathy test verifies this extension path; no empathy
or fluency vectors have been extracted or published by this change.

## Verification

```bash
uv run pytest tests/lab tests/website_api
node --test website/frontend/tests/*.test.js
# Start the website first; verifies actual Qwen routing and baseline isolation.
uv run python research/steering_experimentation/verify_multifeature_api.py \
  --output /tmp/multifeature_api_smoke.json
```

The real-model smoke test covers two features at one layer, independent layers
with different pooling, exact plan-to-result metadata, and an identical baseline
before/after steering. It measures integration and isolation, not response quality.
