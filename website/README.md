# SecondThought website

The target experimental backend is specified in the
[Steering Lab backend design](../docs/STEERING_LAB_BACKEND_DESIGN.md). It defines
the proposed catalogs, immutable experiment/run contracts, model adapters,
evaluation lifecycle, live graph series, and phased migration. Those planned
capabilities are separate from the current API documented below.

The website is a local FastAPI application serving a static HTML/CSS/JavaScript
frontend and the finalized Qwen activation-steering implementation. It does not
import Gradio, the extension API, or any fine-tuned T5 model.

## Run

**New machine or PR reviewer?** Start with the [local setup and testing guide](../docs/LOCAL_TESTING.md),
including the offline artifact preflight and tests of the three steering features.

From the repository root:

```bash
uv sync --python 3.12 --locked --extra evaluation
uv run --locked python -m website.api.check_setup
uv run --locked python -m website.api.server
```

`--extra evaluation` installs the models the response inspector scores with
(Detoxify and sentence-transformers). Without it the site still runs, but the
inspector shows "Scoring unavailable". Plain `uv sync` removes extras you don't
name, so keep the flag on every sync. The first start downloads the scoring
models (about 1.5 GB); until they load, the inspector shows "Scoring loading…".

No `make` (e.g. on Windows)? Run `uv run python -m website.api.server` instead.
The same goes for the extension's service: `uv run python -m extension.api.server`.

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

The Community page (`/community`) is the extension's home, written for people
who have never opened a terminal. Its big button downloads a double-click setup
file for the visitor's system (`/downloads/SecondThought-Setup-Windows.cmd`, or
`/downloads/SecondThought-Setup-macOS.zip`, which keeps the `.command` file
runnable). Both just run the installers in `scripts/`. Three short steps and an
FAQ follow. The terminal commands and the manual zip sit in a folded "For
developers" section: `/downloads/secondthought-extension.zip` zips
`extension/frontend/` on the fly (plus a short `HOW TO INSTALL.txt`), so it's
always the current version. The guide also checks live whether the extension's
service is running.

Both point at this machine for now. Once we deploy, set these instead of
changing code:

- `SECONDTHOUGHT_EXTENSION_DOWNLOAD_URL`: where the download button goes
- `SECONDTHOUGHT_EXTENSION_API_URL`: the service the guide checks (default `http://127.0.0.1:8000`)
- `SECONDTHOUGHT_INSTALLER_BASE_URL`: where the install commands fetch the scripts from (default: `scripts/` on GitHub master)

On the extension side, `SECONDTHOUGHT_WEBSITE_ORIGINS` (extension API) and
`SITE_URL` (`extension/frontend/settings.js`) are the matching switches.

## Pages and layer controls

- **Home** (`/`): product overview with links to the free extension and Steering Lab.
- **Explore** (`/explore`): animated 24-layer schematic above the live draft/rewrite
  comparison. Click a layer to inspect it, check **Select layer** to include it,
  and set its independent alpha from -2 to +2. Default: layer 11 at +0.5.
- **Community** (`/community`): the extension's home, with the download and a
  setup guide (see "The extension download" above).
- **Evaluation** (`/evaluation`): results dashboard for `both-t5` on the 35
  workplace messages: pipeline, headline scores, ready to send, light touch and
  before/after.

Legacy `/steering` links redirect to Explore; `/extension` and `/about`
redirect to Community. Only Explore loads the generation JavaScript. Shared
styles live in `assets/styles.css`; `assets/lab.css` is a retained legacy asset
and is no longer loaded.

Explore also loads `assets/experiment.css` for its setup controls and response
inspector. On desktop the setup is a left rail, the layer diagram and live draft/
output occupy the center, and observations span the full width beneath both blocks. Smaller screens
reflow the panels. Feature × pooling chooses one of fourteen checked vector families.
The model is fixed; task presets and custom system instructions are live. Open
**Instructions & limits** to edit the exact system prompt and token budgets,
then press **Apply**. Typing in the editor does not change a running experiment
until Apply is pressed. Choosing a task preset applies it immediately.

The inspector has keyboard-accessible Metrics, Curves, and Run details tabs.
Run metadata and original-input word comparisons are live. Each completed response
is scored through `POST /api/v2/lab/score` with the same models as the evaluation
pipeline: formality (`s-nlp/roberta-base-formality-ranker`), toxicity (Detoxify
`original`) and, for Rewrite, meaning kept (`all-mpnet-base-v2`, cut-off 0.90) and
facts kept (numbers, dates, times and names). Curves plots each response's formality
and toxicity over time. Sweep execution and zero-baseline comparison are not
connected; the UI does not manufacture values or send unsupported request fields.
Opening the prompt display or changing inspector tabs never starts generation.

Available directions come from the existing artifacts, never synthetic vectors:

The website now loads its compatibility map from the checked catalog under
`artifacts/catalog/`. All 24 decoder indices are available. The entries below
remain the unchanged defaults at their existing layers; every other index uses
the new experimental mean-pooled formality vector. The complete catalog contains
336 feature × layer × pooling directions plus five references, covering Formality,
Detoxification, Fluency, Simplification, Conciseness, Empathy and Politeness.
See [extraction and validation details](../research/steering_experimentation/ALL_LAYER_CATALOG.md).
Fluency preparation, provenance, limitations and reproduction commands are in
the [fluency extraction guide](../docs/FLUENCY_EXTRACTION.md).

Continue uses assistant-prefill completion: the supplied passage starts an open
assistant turn, and only tokens generated after that passage are returned and
streamed. A fixed user instruction asks the model to extend that passage. The
passage and instructions both count toward the input budget. Resolved/completed
run metadata records `prompt_format` and its instruction; Run details displays
it alongside the system instruction. Other tasks, including Custom, retain
normal user-message input. Restart the server and reload the page after changing
task presets; the serving version invalidates older cached results.

**Rewrite & continue** runs two stages in one scheduled job: rewrite the original
input, then generate a new paragraph from the rewritten text. Both stages apply
the same selected intervention plan. The rewrite can use at most half the output
budget; the continuation receives the remaining generated-token budget. A rewrite
that hits its limit is returned as a partial result without appending to it.
Cancellation and the generation deadline apply to the whole job. Run details
and resolved metadata include both instructions and the rendering strategy.
New continuation text can introduce ideas; it is not a meaning-preserving rewrite.

The feature mixer shows Formality, Fluency, Empathy and Politeness. Click a feature name to toggle it; inactive features have half opacity. The left setup rail has been removed; Task opens the task and instruction controls. The four-axis spider-web controls strengths. Drag coloured points along
their axes, or focus a point and use arrow keys (Home/End select the bounds).
The centre means −2, the middle ring means 0, and the outer ring means +2. Disabled
features display `Off` and do not enter generation. Each point edits only that
feature's focused layer; other selected layers retain their strengths. **Layer
controls** opens precise sliders and the complete saved-layer lists. The web is
a schematic of the settings, not measured geometry between activation vectors.

See the [feature pipeline guide](../docs/FEATURE_EXTRACTION.md) for sources,
preparation, extraction and validation of the four latest features. **Dataset &
direction** shows provenance for the exact selected artifact. Empathy and
politeness use derived span/marker contrasts; no broad behavioral reliability
claim follows from their held-out ordering scores.

| Layer (zero-based) | Direction | Artifact candidate | Scale |
| --- | --- | --- | --- |
| 0 | Detoxification | `best_mean` | Unit norm |
| 4 | Formality | `alternative_layer4_final` | Raw |
| 11 | Formality | `negative_layer11_mean` | Raw |
| 21 | Formality | `primary_layer21_mean` | Raw |
| 22 | Detoxification | `best_final` | Unit norm |

If a vector is unavailable, its layer is **preview only** and never enters an
inference request or triggers generation. With the complete current catalog,
every layer has an available default. Clicking a layer adds it immediately; clicking it again removes it. Selected available vectors combine in a single
forward pass at their respective blocks. Magnitudes are not comparable across
raw and normalized directions. These combinations are experimental, not a
validated quality improvement. The layer-11 default preserves the previous lab.
`api/layers.py` projects the catalog for the existing API; shuffled control vectors
are not exposed. Focused vector labels distinguish new experimental vectors from
preserved legacy references.

The moving paths are illustrative, not real activation traces. Motion honors reduced-motion preferences. An optional ? guide explains layer
selection, strengths and preview behavior without persistent tutorial text. Layer buttons support arrow keys,
Home and End; the slider supports native keyboard adjustment. Reset restores
layer 11 at +0.5 and clears other selections. The writing area retains animated
automatic original-to-rewrite word highlights, generation status, and expandable run details.

Greedy decoding remains fixed. With no selected available layers (or all zero
strengths), the model follows the applied task instructions without vector hooks.
Adjacent settings can yield identical wording. Input-based highlights are shown
only for the Rewrite task; other tasks do not treat question/answer differences
as steering effects. Output-limit finishes are labeled and partial results are
not cached. Long responses scroll within the output card.

## Interaction and scheduling

Slider movement updates its numeric readout immediately. Requests start after a
250ms pause, with a maximum scheduling interval of one second during a continuous
drag. Releasing the slider commits the final applied value immediately, clearing
pending scheduling timers. Native keyboard commits use the same path. If that
revision already dispatched during a pause or the maximum-wait interval, release
does not restart it. Preview and unselected layers never flush inference, and
cleared drafts never generate. Typing waits 450ms; input
method composition is respected. These intervals schedule generation; they do not
promise a new completed sentence at every slider position or animation frame.
Immediate submission can still be followed by server queueing or cooperative
cancellation of the previous generation. See [the phase 0 baseline](PHASE_0_BASELINE.md)
for the reference configuration and regression checks used before backend generalization.

Each tab creates an ephemeral UUID and increasing revision numbers. The client
accepts text only for its latest revision. Requested layer strengths and the strengths used for
the displayed result are tracked separately. The previous completed result remains
visible, explicitly labeled, until current text starts streaming. Partial text is
labeled provisional until the response completes.

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
| GET | `/` | Product landing page |
| GET | `/explore` | Interactive steering lab |
| GET | `/community` | Extension introduction |
| GET | `/evaluation` | Empty evaluation page |
| GET | `/health/live` | Process responds |
| GET | `/health/ready` | 200 only after model load; otherwise 503 |
| GET | `/api/v1/steering/config` | Model status, controls, limits, and version |
| GET | `/api/v2/lab/catalog` | Read-only model/feature/vector inventory, provenance, and availability |
| POST | `/api/v2/lab/runs/resolve` | Inspect an exact multi-feature intervention plan without generating |
| POST | `/api/v2/lab/runs` | Generate from a resolved multi-feature configuration |
| POST | `/api/v2/lab/runs/stream` | Stream a multi-feature run with plan/configuration identities |
| POST | `/api/v2/lab/runs/cancel` | Cancel a specific run revision |
| POST | `/api/v1/steering/rewrite` | Complete JSON result |
| POST | `/api/v1/steering/stream` | Newline-delimited JSON event stream |
| POST | `/api/v1/steering/cancel` | Cancel a specific session revision |

The [multi-feature run contract](../docs/MULTIFEATURE_RUNS.md) supports different
layers per feature, multiple features at one layer, independent strengths and
exact artifact selection. Production v1 requests adapt to the same execution
engine. The frontend now uses v2: enable features with the checkboxes, choose
**Edit layers for** to configure independent layers/pooling, and use the
**Feature mix** spider web beside the model. Each draggable point, or precise
slider under **Layer controls**, edits its feature at the displayed layer. The web is not a
measurement of feature angles or activation similarity.

V1 rewrite/stream request:

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

Feature checkboxes enable independent intervention banks. Each feature chooses
its own mean/final-token pooling, layer mode, selected layers and strengths.
**Edit layers for** chooses which bank the layer strip edits; changing it only
changes the view. Colours show that bank's exact vector evidence, while feature
dots and active chips show every enabled bank's interventions. The mixer can
steer Formality and Detoxification together at the same or different layers.
Each mixer row names the edited layer separately from the feature's active-layer
count and peak absolute strength. A disabled edited layer can still have other
layers active. Click the row's summary to inspect all retained strengths or clear
only that feature. Disabled feature sliders show a dash rather than a saved
strength that could be mistaken for an applied value.
Disabling a feature retains its settings; Clear layers clears all banks. Reset
selects only new Formality/mean vectors, layer 11 at +0.5. Legacy compatibility
vectors remain available to older API clients; they are not the lab UI defaults.
Positive strength follows the chosen direction (formal-minus-informal or
neutral-minus-toxic); output quality and meaning preservation remain experimental.

Layer selection uses direct toggles with no mode switch. Each feature can keep
one or several selected layers; each retains its own strength. Arrow keys focus
a layer; Enter or Space toggles its selection. Feature selection and focused-layer
strengths live in Feature mix. Pooling is under Layer controls, and Task contains
presets, custom instructions and token budgets.

The enabled-layer chips show every strength (including zero) and can individually
disable layers. **Clear layers** disables all layers. The count describes only
nonzero shifts; a zero strength registers no hook. Multiple nonzero layers are counted explicitly; the help panel explains that
their shifts are applied together and can degrade generation.
Exact strengths and vector IDs remain the inference contract.
Reset enables only Formality, mean pooling, layer 11 at +0.5.

An optional `layer_vector_ids` map selects exact vectors, for example
`{"11":"qwen-detoxification-l11-mean-v1"}` alongside `layer_strengths`.
Overrides must name available vectors for the matching model/layer and have a
corresponding strength. Omitted entries use the compatibility default. Each
stream event echoes this map; the frontend includes it in cache keys and run
details. Feature and pooling changes update generation automatically while
preserving selected layers and their strengths. Legacy callers can still use
this map. The frontend uses v2 intervention lists, which preserve multiple
features at a shared layer without collapsing them into one layer-map entry.

Use a new, higher revision for every request in a session. Messages must be
nonblank and at most 20,000 characters. The full formatted prompt (instructions,
input and chat markers) has a default 2,048-token budget, adjustable from 128 to
4,096. Output defaults to 128 tokens for Rewrite and 256 for other UI presets,
adjustable from 32 to 512. Overflow is rejected without silent truncation; the
runtime also checks the model context window. Only beta=0 is accepted.
Strengths must be finite and within range; unknown fields are rejected.

Task controls are defined in `website/api/prompts.py` and rendered from the same
server-owned presets and limits. Requests optionally supply:

```json
{
  "task": "summarize",
  "max_input_tokens": 4096,
  "max_new_tokens": 256
}
```

Omitting `system_prompt` resolves the chosen preset; for `task:"custom"` supply
an explicit nonblank instruction (up to 4,000 characters). Preset labels must
match their exact instructions; edited instructions use `custom`. For
`task:"none"`, `system_prompt` is null and the Qwen template's automatic default
system instruction is explicitly removed. The user message still provides the
task. No conversation history is retained.

Every stream event echoes task, exact instructions and budgets. These settings
participate in client cache keys and completed run details. The website worker
allows 90 seconds per generation; client requests time out after 110 seconds.
Per-request output budgets never mutate the shared model's generation defaults.
The extension and Gradio retain their existing defaults.

Completed runs and config expose actual runtime device/dtype; Run details displays
them. The loader uses float32 on MPS/CPU and float16 on CUDA. To investigate
repetition, compare Clear layers against the same input, task, prompt and budgets,
then add interventions individually. Precision remains a separate variable; a
loop under combined steering does not by itself establish a dtype regression.

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

## Layer selection colours

The lab loads its JavaScript module tree and styles through a content-versioned
asset prefix. Asset responses require cache revalidation, preventing stale
control scripts from being reused with updated option values. Restart the
server after backend changes and refresh the page to load the current build.

Layer tiles are neutral until selected. Selected tiles use the feature's colour:
purple for Formality, orange for Fluency, pink for Empathy and teal for Politeness.
Layers selected for multiple enabled features show coloured stripes. Turning a
feature off removes its colour while retaining its saved settings. Colours do
not encode strength or quality. Layer indices remain visible; accuracy scores
and the heat legend are no longer displayed.

Held-out measurements remain in the backend catalog and research artifacts;
this presentation change does not modify vector extraction or interventions.

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
