# SecondThought for Chrome

A small Chrome extension for trying SecondThought on real messages. Paste or
select a message, hit **Second thought?**, and copy the rewrite.

The extension doesn't run any model itself. It sends the text to a tiny local
server (`api/server.py`), which uses the same `build_rewriter()` as the CLI and
the Gradio app. By default that server runs **our own fine-tuned `both-t5`
model** on your CPU, so nothing leaves your machine and no API key is needed.

```text
popup  ──POST /rewrite──▶  api/server.py  ──▶  build_rewriter(load_settings("config/t5.toml"))
                                               both-t5 "detoxify: "  ──▶  both-t5 "formalize: "
```

`both-t5` is one T5-small trained on ParaDetox and GYAFC together
(`notebooks/train_both.ipynb`). The prefix picks the job, so each sentence goes
through it twice: first to drop insults and swearing, then to fix the wording
and register.

A **facts guard** runs after each step. If a step drops or changes a number,
date, amount or similar (say "2.5%" becoming "2,5%"), that sentence keeps its
previous wording. On the 35 workplace messages this keeps 100% of critical
values. The steps and the guard live in `config/t5.toml`, so you can change
them without touching code.

## Running it

You need Python 3.12+ and the project installed as described in the main
README (`uv sync` is the easiest route).

**1. Put the model in place.** The server expects the exported `both-t5`
folder (it's git-ignored, so get it from the team drive or from
`train_both.ipynb`):

```text
models/both-t5/    config.json, model.safetensors, tokenizer files...
```

**2. Start the server** from the repo root and leave it running:

```bash
python -m api.server
```

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
3. Click **Load unpacked** and pick this `extension/` folder
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

On Gmail, Slack, Teams, Outlook, LinkedIn and GitHub you don't need to open
the popup. Type as usual. If the message has swearing, insults, texting
shorthand ("u", "ur", "gonna") or shouting, a small **SecondThought?** pill
appears in the corner of the text box.

- **Spotting is local.** `triggers.js` is a word list and a few patterns
  that run inside the page about 0.6 s after you stop typing. Nothing you type
  leaves the page, and no model runs, until you click the pill.
- **Clicking the pill** sends that text to the local server, and a card shows
  the suggestion with removed words struck out and new ones highlighted.
  **Replace** swaps it in (Ctrl+Z or **Undo** brings yours back), **Copy**
  copies it, **Dismiss** hides the pill until new trigger words show up.
- **Select part of your message first** to rewrite only that part. Handy in
  Gmail, where the box can also hold a quoted reply.
- **Turn it off per site** with "Don't suggest on this site" in the card, and
  back on with the checkbox at the bottom of the popup.

The page can't call the local server directly (sites block requests to
`127.0.0.1`), so the request goes through the extension's background worker
(`background.js`).

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

- The nudge only runs on the six sites above, and it suggests rather than
  intercepting the Send button.
- The trigger list is hand-written, and the last few insults were added after
  looking at our own 35-message set, so expect misses on new kinds of
  hostility (sarcasm, passive aggression).
- Gmail and Slack were tested with a stand-in page, not on the live sites.
  Their editors are complex, so Replace there needs a real-world check.
- The T5 models only make word-level edits, so rhetorical jabs ("Did you even
  test this?", "Stop ignoring me") get through.
- The facts guard only protects values it can extract (numbers, dates,
  amounts…). Meaning changes in plain words, like "b4 the mtg" becoming "with
  the Mtg", still slip through.
- Sentence splitting is a simple punctuation rule, so things like "e.g." can
  split a sentence in the wrong place.
- The server address is hardcoded to `127.0.0.1:8000`.
