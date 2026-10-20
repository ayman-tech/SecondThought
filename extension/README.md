# SecondThought for Chrome

A small Chrome extension for trying SecondThought on real messages. Paste or
select a message, hit **Second thought?**, and copy the rewrite.

The extension doesn't run any model itself. It sends the text to a tiny local
server (`api/server.py`), which uses the same `build_rewriter()` as the CLI and
the Gradio app. By default that server runs **our own fine-tuned T5-small
models** on your CPU, so nothing leaves your machine and no API key is needed.

```text
popup  ──POST /rewrite──▶  api/server.py  ──▶  build_rewriter(load_settings("config/t5.toml"))
                                               ParaDetox T5  ──▶  GYAFC formal T5
```

Each sentence goes through ParaDetox first (drops insults and swearing), then
the GYAFC formality model (fixes the wording and register). The steps live in
`config/t5.toml`, so you can reorder them or drop one without touching code.

## Running it

You need Python 3.12+ and the project installed as described in the main
README (`uv sync` is the easiest route).

**1. Put the models in place.** The server expects the two exported model
folders (they're git-ignored, so get them from the team drive or from the
training notebooks):

```text
models/t5-small-paradetox/       config.json, model.safetensors, tokenizer files...
models/t5-small-gyafc-formal/    same files
```

**2. Start the server** from the repo root and leave it running:

```bash
python -m api.server
```

Loading both models takes a few seconds. Then it listens on
`http://127.0.0.1:8000`. A quick check:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","model":"t5-small: detox -> formal"}
```

If you see `"status":"error"`, the detail says what's wrong, usually a
missing model folder.

**3. Load the extension.**

1. Go to `chrome://extensions`
2. Switch on **Developer mode** (top right)
3. Click **Load unpacked** and pick this `extension/` folder
4. Pin SecondThought from the puzzle-piece menu so it's one click away

Open the popup. The small dot in the corner is green when the server is
reachable and red when it isn't. Hovering it shows which model is loaded.

## Quick manual test (about 30 seconds)

These are what the T5 setup gives today. It keeps facts, numbers and
deadlines very reliably, but it only makes small edits. It won't soften
sentence-level jabs the way GPT does.

1. `U r a brainless idiot for not doing the job on time`
   becomes *"You are a brainless person for not doing the job on time."*
   The insult and the texting style go away.

2. `Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.`
   "stupid" is dropped. **20 times** and **before merging** stay. "Did you
   even test this?" stays too, which is a known gap.

3. `This function silently drops failed records. Please add error handling before approving the pull request.`
   Comes back unchanged, and the line under the result says "Already
   professional, so no changes."

Then stop the server and click **Second thought?** again. You should get a
red note saying the server can't be reached.

You can also select text on a page (a Gmail draft, a Slack message box) before
opening the popup, and it will be filled in for you.

## Using OpenAI instead

To compare against the GPT baseline, start the server with the default config
and an `OPENAI_API_KEY` in your shell or `.env`:

```bash
SECONDTHOUGHT_CONFIG=config/default.toml python -m api.server
```

## The API

| Method | Path       | Body                              | Returns |
|--------|------------|-----------------------------------|---------|
| GET    | `/health`  | nothing                           | `{"status": "ok", "model": ...}` or `{"status": "error", "detail": ...}` |
| POST   | `/rewrite` | `{"message": "..."}` (1–4000 chars) | `{"original_text", "rewritten_text", "model_info", "latency_ms"}` |

Errors come back as `{"detail": "..."}`: 400 for a blank message or a sentence
over the T5 limit (128 tokens), 422 for a malformed body, 502 when the model
fails, and 503 when the server couldn't load its models. Only
`chrome-extension://` origins are allowed through CORS.

## Not done yet

- No pre-send nudge inside Gmail or Slack yet. This is the popup only.
- The T5 models only make word-level edits, so rhetorical jabs ("Did you even
  test this?", "Stop ignoring me") get through.
- Sentence splitting is a simple punctuation rule, so things like "e.g." can
  split a sentence in the wrong place.
- The server address is hardcoded to `127.0.0.1:8000`.
