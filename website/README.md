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

Device selection is MPS, CUDA, then CPU. To override:

```bash
SECONDTHOUGHT_WEBSITE_DEVICE=cpu make website
```

No API key, database, npm installation, or frontend build is required. Fonts have
system fallbacks if Google Fonts is unavailable. The server binds to loopback and
is intended for local use; authentication, a public deployment, and infrastructure
are outside this first version. Restart the Python process after backend changes.
The website API currently runs from the repository checkout, not a standalone wheel.

## Current scope and model behavior

- Overview and the formality interface are functional. The other sections explain
  the existing repository workflows and their current limitations.
- Alpha ranges from -2 to +2 in steps of 0.1. Default: +0.5.
- Formality uses the raw GYAFC `negative_layer11_mean` vector at decoder layer 11.
- Beta is fixed to zero for this website. The core still supports independent
  ParaDetox `best_final` steering at layer 22, as in the finalized experiments.
- The fixed neutral prompt and greedy decoding match the finalized notebooks.
- Alpha zero still runs a prompted rewrite. It is not an identity/copy mode.
- Text may remain identical at adjacent strengths. Strong settings may change
  meaning, facts, or who is being asked to act; there is no live reliability score.
- A 64-token completion limit bounds work. If the limit is reached, the page labels
  the result as partial. It is not saved in the result cache.

The original Stitch export is retained as `frontend/code 2.html` for reference.
The server serves only `frontend/index.html` and `frontend/assets/`.

## Interaction and scheduling

Slider movement updates its numeric readout immediately. Requests start after a
250ms pause, with a maximum scheduling interval of one second during a continuous
drag. Releasing the slider flushes the final value. Typing waits 450ms; input
method composition is respected. These intervals schedule generation; they do not
promise a new completed sentence at every slider position or animation frame.

Each tab creates an ephemeral UUID and increasing revision numbers. The client
accepts text only for its latest revision. Requested alpha and the alpha used for
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
source text, alpha, beta, and steering version. It stores only completed results,
is cleared by Clear, and disappears when the page is reloaded. No drafts, account
history, or generated results are written to persistent storage by this service.
The server logs request paths/status and failures, not normal draft text.

Word highlights compare actual generated text with the previous completed result
for that source, or the source on the first run. They are text differences, not
measurements of internal attention or token attribution. All dynamic text is
rendered as DOM text nodes; user/model text is never interpreted as HTML. Reduced
motion, keyboard slider controls, and accessible status messages are supported.
On small screens the slider docks near the bottom while the experiment is in
view, so its output stays visible as you adjust it. It undocks when the draft
field receives focus, leaving space for the on-screen keyboard.

## API

Interactive schema: **http://127.0.0.1:8001/docs**.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Website |
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
  "beta": 0
}
```

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

It exercises real model steering, latest-revision handling, rapid slider changes,
Clear while a response is pending, caching, safe rendering of HTML-like text,
network-error retry, and desktop/mobile layout. Browser fixtures intercept some
requests to reproduce races deterministically; normal product code has no fake
rewrite path. `CHROME_PATH` and `WEBSITE_URL` can override defaults.

Before submitting, try your own sentences at alpha -1, 0, +0.5, and +1; drag quickly,
clear mid-generation, then enter another draft. Review semantic changes as well as
whether the UI stays current. Model quality remains the experimental limitation.
