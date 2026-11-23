# Phase 0: interaction and inference baseline

This is the frozen pre-catalog reference. See the
[all-layer release](../research/steering_experimentation/ALL_LAYER_CATALOG.md) for
current catalog coverage; the legacy tensor references below remain unchanged.

Reference source: `521d5576d3bd5185e37e25d9e974d398e7e27626` (the master revision
from which `nandan/steering-lab-backend` starts).

Phase 0 restores immediate slider commit without changing model execution, vector
artifacts, prompt construction, API schemas, or backend scheduling. Later phases
must preserve the behavior below unless they deliberately version a change.

## Interaction contract

- Input updates the strength readout and invalidates obsolete output immediately.
- During a drag, generation waits 250ms after the latest applied change, with a
  maximum scheduling interval of one second during continuous changes.
- Native slider `change` commits the final applied setting immediately. Pointer,
  touch, and keyboard commits share this browser event; tests exercise keyboard
  and pointer interactions in Chrome.
- Release clears pending scheduling timers. If that revision already dispatched,
  release does not cancel/restart it, including while in flight or after completion.
- A completed cached setting can be restored immediately without inference.
- Preview-only and unselected layers do not generate or flush unrelated typing.
- Typing retains its 450ms debounce. Empty/Clear invalidates work, clears inspection
  and cache, and prevents late responses from repopulating the output.
- Latest revision wins. Copy is disabled for obsolete and incomplete output.
- Highlights compare the completed response to its submitted original draft.
- Immediate submission does not bypass queue admission, model-worker serialization,
  cooperative cancellation, or generation time.

## Reference inference configuration

| Setting | Reference |
| --- | --- |
| Model ID | `Qwen/Qwen2.5-0.5B-Instruct` |
| Decoder blocks | 24, indexed 0–23 |
| Default intervention | Formality, index 11, mean extraction, raw vector, strength +0.5 |
| Default candidate | `negative_layer11_mean` |
| Other formality candidates | Index 4 / final token / raw; index 21 / mean / raw |
| Detoxification candidates exposed by Explore | Index 0 / mean / unit norm; index 22 / final token / unit norm |
| Injection | Forward-hook addition to all token representations at each selected block output |
| Decoding | Greedy (`do_sample=False`), maximum 64 new tokens |
| Complete prompt limit | 384 tokens, rejected rather than silently truncated |
| Precision | MPS and CPU float32; CUDA float16 |
| Steering version | `qwen-multilayer-v3` |

System instruction, followed by the source as a separate user message:

```text
Rewrite the user's sentence while preserving its meaning. Return only the rewritten sentence.
```

With no nonzero interventions, Qwen still follows that prompt. Zero steering is
not an identity transformation. No semantic-preservation guarantee is established.

Artifact SHA-256 checksums:

```text
qwen2_5_0_5b_gyafc_formality_directions.pt
53af037f6f44170568340298215f58f7a71201cc6bc4a1acb861d08ddb88b73f

qwen2_5_0_5b_paradetox_directions.pt
cb08216f6d3ca5c66f3827e93c6429d8d7bc9ff3093d1bf8dfe19f74578cda11
```

These identify the existing files under `artifacts/`. Phase 1 will add machine-readable
catalog/provenance validation and pinned model revisions. This document records
configuration and artifact identity; it does not assert identical outputs across
different devices, model snapshots, or dependency versions.

## Verification

```bash
make website-test
make website
# In another terminal, with Chrome installed:
node website/frontend/tests/browser-smoke.mjs
```

The browser check first runs controlled scheduling timers and delayed response
fixtures against the real frontend. It asserts immediate release before any
debounce callback runs, duplicate suppression after pause/max-wait dispatch,
stale-response rejection, cache restoration, preview/unselected exclusion, Clear,
and native keyboard/pointer commits. Fixtures are restored before checking actual
Qwen generation, multi-layer payloads, original-input highlighting, reset/cache,
and the website pages. Product code contains no fixture generation path.
