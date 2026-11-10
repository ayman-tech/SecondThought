# SecondThought for Chrome

A small Chrome extension for trying SecondThought on real messages. Paste or
select a message, hit **Second thought?**, and copy the rewrite.

This folder holds both halves of the extension:

```text
extension/
  frontend/    the Chrome extension itself (manifest, popup, content scripts)
  api/         its local backend; runs on your machine, never in the cloud
```

The extension doesn't run any model itself. It sends the text to a tiny local
server (`extension/api/server.py`), which uses the same `build_rewriter()` as
the CLI and the Gradio app. By default that server runs **our own fine-tuned
`both-t5` model** on your CPU, so nothing leaves your machine and no API key is
needed.

```text
popup  ──POST /rewrite──▶  extension/api/server.py  ──▶  build_rewriter(load_settings("extension/api/config.toml"))
                                                         both-t5 "detoxify: "  ──▶  both-t5 "formalize: "
```

`both-t5` is one T5-small trained on ParaDetox and GYAFC together
(`research/notebooks/train_both.ipynb`). The prefix picks the job, so each sentence goes
through it twice: first to drop insults and swearing, then to fix the wording
and register.

A **facts guard** runs after each step. If a step drops or changes a number,
date, amount or similar (say "2.5%" becoming "2,5%"), that sentence keeps its
previous wording. On the 35 workplace messages this keeps 100% of critical
values. The steps and the guard live in `extension/api/config.toml`, so you can
change them without touching code.

## Running it

You need Python 3.12+ and the project installed as described in the main
README (`uv sync` is the easiest route).

**1. Put the model in place.** The server expects the exported `both-t5`
folder (it's git-ignored, so get it from the team drive or from
`research/notebooks/train_both.ipynb`):

```text
models/both-t5/    config.json, model.safetensors, tokenizer files...
```

**2. Start the server** from the repo root and leave it running:

```bash
make                            # shortcut for the line below
python -m extension.api.server
```

`make extension-api-health` checks that it's up.

Loading the model takes a few seconds. Then it listens on
`http://127.0.0.1:8000`. A quick check:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","model":"both-t5: detox -> formal"}
```

If you see `"status":"error"`, the detail says what's wrong, usually a
missing model folder.

**3. Load the extension.**

1. Go to `chrome://extensions`
2. Switch on **Developer mode** (top right)
3. Click **Load unpacked** and pick the **`extension/frontend/`** folder (the one
   that contains `manifest.json`, not `extension/` itself)
4. Pin SecondThought from the puzzle-piece menu so it's one click away

Open the popup. The small dot in the corner is green when the server is
reachable and red when it isn't. Hovering it shows which model is loaded.

## Quick manual test (about 30 seconds)

These are what the T5 setup gives today. It keeps facts, numbers and
deadlines very reliably, but it only makes small edits. It won't soften
sentence-level jabs the way GPT does.

1. `U r a brainless idiot for not doing the job on time`
   becomes *"You are not a good person for not doing the job on time."*
   The insult and the texting style go away.

2. `Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.`
   "stupid" is dropped. **20 times** and **before merging** stay. "Did you
   even test this?" stays too, which is a known gap.

3. `That report is garbage. The defect rate went from 2.5% to 4%, and you somehow called that an improvement.`
   becomes *"That report is not good. …"* with **2.5%** and **4%** untouched.
   Without the facts guard the model writes "2,5%".

4. `This function silently drops failed records. Please add error handling before approving the pull request.`
   Comes back unchanged, and the line under the result says "Already
   professional, so no changes."

Then stop the server and click **Second thought?** again. You should get a
red note saying the server can't be reached.

You can also select text on a page (a Gmail draft, a Slack message box) before
opening the popup, and it will be filled in for you.

## The "SecondThought?" nudge

On any website you don't need to open the popup. Type as usual. If the message has swearing, insults, texting
shorthand ("u", "ur", "gonna") or shouting, a small **SecondThought?** pill
appears in the corner of the text box.

- **Spotting is local.** `triggers.js` is a word list and a few patterns
  that run inside the page about 0.6 s after you stop typing. Nothing you type
  leaves the page, and no model runs, until you click the pill.
- **Clicking the pill** sends only the lines that set off a trigger to the local
  server, and a card shows the suggestion with removed words struck out and new
  ones highlighted. Signatures, quoted replies and every other line stay
  exactly as they are.
- **Replace** swaps it in, and **Undo** brings it all back in one click (Ctrl+Z
  also works, one line at a time). **Copy** copies it. **Dismiss** quiets the
  pill until you write a new sentence with a trigger in it.
- **Select part of your message first** to rewrite just that part instead.
- **Turn it off for a site** with the "Suggest while typing on <site>" switch
  in the popup. It's on by default everywhere.

## The popup and settings

- **The popup** shows the suggestion with the same struck-out and highlighted
  words, a **Spotted** row with what was flagged ("lazy · harsh"), and a
  **Kept as written** row with the numbers, dates and amounts the rewrite kept.
- **More settings** (or Chrome's extension options) opens a settings page to
  switch the pill off everywhere, choose what triggers it (swearing, harsh
  words, texting shorthand, shouting), turn sites back on, and check whether
  the server is running.
- All of these read the same values from `settings.js`, so a change in one
  shows up in the others straight away.

The page can't call the local server directly (sites block requests to
`127.0.0.1`), so the request goes through the extension's background worker
(`background.js`).

## Using OpenAI instead

To compare against the GPT baseline, start the server with the default config
and an `OPENAI_API_KEY` in your shell or `.env`:

```bash
SECONDTHOUGHT_CONFIG=config/default.toml python -m extension.api.server
```

## The API

| Method | Path       | Body                              | Returns |
|--------|------------|-----------------------------------|---------|
| GET    | `/health`  | nothing                           | `{"status": "ok", "model": ...}` or `{"status": "error", "detail": ...}` |
| POST   | `/rewrite` | `{"message": "..."}` (1–4000 chars) | `{"original_text", "rewritten_text", "model_info", "latency_ms", "kept_values"}` |

Errors come back as `{"detail": "..."}`: 400 for a blank message or a sentence
over the T5 limit (128 tokens), 422 for a malformed body, 502 when the model
fails, and 503 when the server couldn't load its models. Only
`chrome-extension://` origins are allowed through CORS.

## Not done yet

- The nudge suggests rather than intercepting the Send button. Because it can
  run on every site, Chrome warns at install that it can read and change data
  on all websites; spotting stays inside the page, and text only goes to your
  local server when you click the pill.
- The trigger list is hand-written, and the last few insults were added after
  looking at our own 35-message set, so expect misses on new kinds of
  hostility (sarcasm, passive aggression).
- Replace was checked in live Gmail. Slack and other sites have only been
  tested on a stand-in page.
- The T5 models only make word-level edits, so rhetorical jabs ("Did you even
  test this?", "Stop ignoring me") get through.
- A sentence that's only an insult ("IDIOT!") is dropped when the message says
  something else too. If it's the whole message, the model still answers with
  something odd ("I do not like it.").
- The facts guard only protects values it can extract (numbers, dates,
  amounts…). Meaning changes in plain words, like "b4 the mtg" becoming "with
  the Mtg", still slip through.
- Sentence splitting is a simple punctuation rule, so things like "e.g." can
  split a sentence in the wrong place.
- The server address is hardcoded to `127.0.0.1:8000`.
