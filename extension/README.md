# SecondThought for Chrome

A small Chrome extension for trying SecondThought on real messages. Paste or
select a message, hit **Second thought?**, and copy the rewrite.

The extension doesn't talk to OpenAI itself. It sends the text to a tiny local
server (`api/server.py`), and that server uses the same rewriter, config and
prompt as the CLI and the Gradio app. That way the API key never ends up in the
browser, and swapping the model later doesn't touch the extension.

```text
popup  ──POST /rewrite──▶  api/server.py  ──▶  build_rewriter(load_settings())
                                               config/default.toml + prompts/
```

## Running it

You need Python 3.12+ and the project installed as described in the main
README. `uv sync` is the easiest route; `pip install -e ".[dev]"` in a venv
works too.

**1. Add your key.** Copy `.env.example` to `.env` and fill in
`OPENAI_API_KEY`. The server reads the key from your shell first and falls
back to `.env`, so on Windows you don't need to `source` anything.

**2. Start the server** from the repo root and leave it running:

```bash
python -m api.server
```

It listens on `http://127.0.0.1:8000`. A quick check:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","model":"gpt-4.1-mini-2025-04-14"}
```

If you see `"status":"error"` instead, the detail tells you what's missing
(almost always the key).

**3. Load the extension.**

1. Go to `chrome://extensions`
2. Switch on **Developer mode** (top right)
3. Click **Load unpacked** and pick this `extension/` folder
4. Pin SecondThought from the puzzle-piece menu so it's one click away

Open the popup. The small dot in the corner is green when the server is
reachable and red when it isn't.

## Quick manual test (about 30 seconds)

Try these three with the server running:

1. **The harsh one.**
   `Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.`
   The dig ("did you even test this?") and "stupid" should be gone. What
   must survive: the retry loop, **20 times**, and the request to
   **replace it before merging**. It should still read as a firm ask, not a
   suggestion.

2. **Urgent, with a deadline.**
   `I've asked you twice already. Stop ignoring me and send the report by 5 PM today.`
   "Stop ignoring me" should be softened, but **twice**, **the report** and
   **5 PM today** should all still be there, and it should still sound urgent.

3. **Already fine.**
   `This function silently drops failed records. Please add error handling before approving the pull request.`
   This should come back unchanged or nearly so. If it's identical, the line
   under the result says "Already professional, so no changes."

Then stop the server and click **Second thought?** again. You should get a
red note saying the server can't be reached, not a spinner that never ends.

You can also select text on a page (a Gmail draft, a Slack message box) before
opening the popup, and it will be filled in for you. Pages like
`chrome://` ones don't allow this, so just paste there.

## The API

| Method | Path       | Body                              | Returns |
|--------|------------|-----------------------------------|---------|
| GET    | `/health`  | nothing                           | `{"status": "ok", "model": ...}` or `{"status": "error", "detail": ...}` |
| POST   | `/rewrite` | `{"message": "..."}` (1–4000 chars) | `{"original_text", "rewritten_text", "model_info", "latency_ms"}` |

Errors come back as `{"detail": "..."}`: 400 for a blank message, 422 for a
malformed body, 502 when the model call fails, and 503 when the server started
without a key. Only `chrome-extension://` origins are allowed through CORS.

`SECONDTHOUGHT_MODEL` and `SECONDTHOUGHT_PROMPT` work here the same way they do
for the CLI, and `SECONDTHOUGHT_CONFIG` points the server at a different config
file.

## Not done yet

- No pre-send nudge inside Gmail or Slack yet. This is the popup only.
- The server address is hardcoded to `127.0.0.1:8000`.
- It only runs locally; nothing is hosted.
