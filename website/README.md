# SecondThought website

The website is a local FastAPI application serving a static HTML/CSS/JavaScript
frontend and the finalized Qwen activation-steering implementation. It does not
import Gradio, the extension API, or any fine-tuned T5 model.

## Run

From the repository root:

```bash
uv sync
make website
```

Open **http://127.0.0.1:8001**. The extension's separate API keeps port 8000.
The page serves while the model initializes and reports readiness automatically.
The first model load may download Qwen from Hugging Face; later launches prefer
the local snapshot. Runtime directions come from the root `artifacts/` directory.

Device selection is MPS, CUDA, then CPU. MPS and CPU use float32; CUDA uses
float16. MPS float16 caused baseline repetition on the tested Mac runtime.
To override:

```bash
SECONDTHOUGHT_WEBSITE_DEVICE=cpu make website
```

No API key, database, npm installation, or frontend build is required. Fonts have
system fallbacks if Google Fonts is unavailable. The server binds to loopback and
is intended for local use; authentication, a public deployment, and infrastructure
are outside this first version. Restart the Python process after backend changes.
The website API currently runs from the repository checkout, not a standalone wheel.

## The extension download

The Community page (`/community`) is the extension's home: a download button and
a four-step setup guide. `/downloads/secondthought-extension.zip` zips
`extension/frontend/` on the fly (plus a short `HOW TO INSTALL.txt`), so it's
always the current version. The guide also checks live whether the extension's
service is running.

Both point at this machine for now. Once we deploy, set these instead of
changing code:

- `SECONDTHOUGHT_EXTENSION_DOWNLOAD_URL`: where the download button goes
- `SECONDTHOUGHT_EXTENSION_API_URL`: the service the guide checks (default `http://127.0.0.1:8000`)

On the extension side, `SECONDTHOUGHT_WEBSITE_ORIGINS` (extension API) and
`SITE_URL` (`extension/frontend/settings.js`) are the matching switches.

## Pages and layer controls

- **Explore** (`/explore`): animated 24-layer schematic above the live draft/rewrite
  comparison. Click a layer to inspect it, check **Select layer** to include it,
  and set its independent alpha from -2 to +2. Default: layer 11 at +0.5.
- **Community** (`/community`): extension introduction. Download is deliberately
  disabled until packaging is ready.
- **Evaluation** (`/evaluation`): empty content area for the upcoming evaluation UI.

Old `/` and `/steering` links redirect to Explore; `/extension` and `/about`
redirect to Community. Only Explore loads the generation JavaScript. Shared
styles live in `assets/styles.css`; `assets/lab.css` is a retained legacy asset
and is no longer loaded.

Available directions come from the existing artifacts, never synthetic vectors:

| Layer (zero-based) | Direction | Artifact candidate | Scale |
| --- | --- | --- | --- |
| 0 | Detoxification | `best_mean` | Unit norm |
| 4 | Formality | `alternative_layer4_final` | Raw |
| 11 | Formality | `negative_layer11_mean` | Raw |
| 21 | Formality | `primary_layer21_mean` | Raw |
| 22 | Detoxification | `best_final` | Unit norm |

Other layers can be selected and adjusted as **preview only**. They never enter
an inference request or trigger generation. Clicking a layer only inspects it;
the checkbox controls selection. Selected available vectors combine in a single
forward pass at their respective blocks. Magnitudes are not comparable across
raw and normalized directions. These combinations are experimental, not a
validated quality improvement. The layer-11 default preserves the previous lab.
The map is in `api/layers.py`; shuffled control vectors are not exposed.

The moving paths are illustrative, not real activation traces. Motion honors reduced-motion preferences. An optional ? guide explains layer
selection, strengths and preview behavior without persistent tutorial text. Layer buttons support arrow keys,
Home and End; the slider supports native keyboard adjustment. Reset restores
layer 11 at +0.5 and clears other selections. The writing area retains animated
original-to-rewrite word highlights, copy, live status, and expandable run details.

The neutral rewrite prompt and greedy decoding are unchanged. With no selected
available layers (or all zero strengths), the prompted model still rewrites.
Adjacent settings can yield identical wording. Review meaning, names, numbers,
and intent; validation of combinations remains future work. The 64-token output
limit is labeled when reached, and partial results are not cached.

## Interaction and scheduling

Slider movement updates its numeric readout immediately. Requests start after a
250ms pause, with a maximum scheduling interval of one second during a continuous
drag. The final value runs after the same short pause. Typing waits 450ms; input
method composition is respected. These intervals schedule generation; they do not
promise a new completed sentence at every slider position or animation frame.

Each tab creates an ephemeral UUID and increasing revision numbers. The client
accepts text only for its latest revision. Requested layer strengths and the strengths used for
the displayed result are tracked separately. The previous completed result remains
visible, explicitly labeled, until current text starts streaming. Copy is disabled
for stale and incomplete streams.

The server admits one active generation and up to eight pending sessions. Each
session has at most one pending job; newer revisions replace older ones. Requests
for an active session cancel its old generation at a decoding boundary. Jobs from
other sessions retain their place in the queue. Browser disconnects and explicit
cancellation also stop queued/running work. A worker must exit its steering hook
context and release its lock before another generation begins.

Generation has a 25-second cooperative timeout (checked between decoding steps);
the browser request has a 35-second timeout. These cannot interrupt a hung device
kernel. Session revision records expire after ten inactive minutes, with a maximum
of 128 records. Restarting the process resets all sessions.

The result cache is a bounded, 24-entry LRU in browser memory, keyed by exact trimmed
source text, all applied layer strengths, legacy alpha/beta, and steering version. It stores only completed results,
is cleared by Clear, and disappears when the page is reloaded. No drafts, account
history, or generated results are written to persistent storage by this service.
The server logs request paths/status and failures, not normal draft text.

Word highlights always compare completed generated text with the original source
draft submitted for that response. Identical responses at different alpha values,
cached responses, and toggling highlights retain the same source comparison.
They are text differences, not
measurements of internal attention or token attribution. All dynamic text is
rendered as DOM text nodes; user/model text is never interpreted as HTML. Reduced
motion, keyboard slider controls, and accessible status messages are supported.

## API

Interactive schema: **http://127.0.0.1:8001/docs**.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/explore` | Interactive steering lab |
| GET | `/community` | Extension introduction |
| GET | `/evaluation` | Empty evaluation page |
| GET | `/health/live` | Process responds |
| GET | `/health/ready` | 200 only after model load; otherwise 503 |
| GET | `/api/v1/steering/config` | Model status, controls, limits, and version |
| POST | `/api/v1/steering/rewrite` | Complete JSON result |
| POST | `/api/v1/steering/stream` | Newline-delimited JSON event stream |
| POST | `/api/v1/steering/cancel` | Cancel a specific session revision |

Rewrite/stream request:

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "revision": 1,
  "message": "its really hard when u want to know what happened",
  "alpha": 0.5,
  "beta": 0,
  "layer_strengths": {"4": 0.3, "11": 0.5}
}
```

`layer_strengths` is the authoritative map when supplied. An empty map means
no vector hooks. Omitting it retains the legacy layer-11 alpha behavior.
Unavailable layer indices are rejected. The frontend sends alpha equal to the
layer-11 setting (or zero if deselected) for compatibility. Events also include
`layer_strengths`, so consumers can identify the settings used.

Use a new, higher revision for every request in a session. Messages must be
nonblank and at most 2,000 characters. The worker also limits the complete chat
prompt to 384 tokens without silently truncating input. Only beta=0 is accepted.
Strengths must be finite and within range; unknown fields are rejected.

Stream events are `queued`, `started`, `delta`, then one of `completed`,
`cancelled`, or `error`. Every event carries `revision`, `request_id`, `alpha`, and
`beta`. `completed` additionally carries `rewritten_text`, `generated_tokens`,
`finish_reason` (`stop` or `length`), measured `latency_ms`, `model_id`, and
`steering_version`. Delta text is provisional; the completed text is authoritative.

Validation/admission failures use HTTP 422, 409 (stale revision), 429 (busy), or
503 (not ready). Once a stream starts, worker errors are terminal JSON events,
since the HTTP headers have already been sent. Do not treat HTTP 200 alone as a
successful completed generation. The JSON endpoint maps worker failures to HTTP
422/500/504. Cancellation contains only `session_id` and `revision` and cannot
cancel a newer revision. The UUID routes work between tabs; it is not authentication.

## Verify

```bash
make website-test
uv run pytest -k 'not real_model_ranks_formal_above_informal'
# Requires the model; checks the notebook functions on the same device.
uv run python research/steering_experimentation/verify_qwen_integration.py --device cpu
```

Optional automated browser QA uses installed Chrome and Node 22+ without npm
packages. Start `make website` first:

```bash
node website/frontend/tests/browser-smoke.mjs
```

It exercises real generation, independent layer strengths, preview exclusion,
source-based word highlights, reset/cache, Clear, reduced motion and all three
pages. Screenshots are saved to a temporary directory printed on completion.
`CHROME_PATH` and `WEBSITE_URL` can override defaults.

Before submitting, try your own sentences at alpha -1, 0, +0.5, and +1; drag quickly,
clear mid-generation, then enter another draft. Review semantic changes as well as
whether the UI stays current. Model quality remains the experimental limitation.
