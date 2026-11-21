# Run and test the Steering Lab locally

## Requirements

- Git and `uv` installed; `uv --version` should succeed.
- Python 3.12, which uv can install with the command below.
- Internet for the initial dependency and Qwen downloads. No OpenAI API key,
  Hugging Face token, database, npm installation or frontend build is required
  for the public Qwen model and local lab.
- A browser. GPU hardware is optional: Apple Silicon uses MPS when available;
  CPU is supported and can be slower, especially with longer inputs/outputs.

The lockfile installs CPU PyTorch on Linux/Windows. Selecting `cuda` does not
turn that build into a CUDA build. CUDA installation is not covered by this
quickstart. Device auto-selection is MPS, then available CUDA, then CPU.

The commands below are run from the **repository root**, except where a directory
change is explicitly shown. They do not require activating a virtual environment.

## 1. Get the correct code

```bash
git clone <repository-url> SecondThought
cd SecondThought
git switch nandan/steering-lab-backend
```

Replace `<repository-url>` with this repository's clone URL. Before the PR is
merged, use its branch above. After it is merged, use the destination branch
containing that PR. An older master checkout will not contain these controls.

## 2. Install the locked environment

```bash
uv python install 3.12
uv sync --python 3.12 --locked
```

This creates `.venv/` and installs the project and development test dependencies.
The dependency download can take time; the repository also includes research
dependencies. It does not download Qwen weights during this step.

## 3. Check the vector artifacts

```bash
uv run --locked python -m website.api.check_setup
```

Expected: **5 verified artifacts and 149/149 available vectors**, with exit code
zero. This checks checksums, tensor shapes and catalog compatibility without
loading or downloading the language model. For a machine-readable report, add
`--json`.

These files are included in the PR branch and must remain at these paths:

```text
artifacts/catalog/qwen2_5_0_5b.json
artifacts/qwen2_5_0_5b_gyafc_formality_directions.pt
artifacts/qwen2_5_0_5b_paradetox_directions.pt
artifacts/qwen2_5_0_5b_formality_all_layers_v1.pt
artifacts/qwen2_5_0_5b_detoxification_all_layers_v1.pt
artifacts/qwen2_5_0_5b_fluency_all_layers_v1.pt
```

You do **not** need the GYAFC corpus, ParaDetox CSV, IteraTeR corpus, extraction notebooks, T5
weights or the extension service to run the Steering Lab. Do not regenerate
directions to repair a missing artifact; restore the files from the same branch
as the catalog manifest.

## 4. Start the website

```bash
uv run --locked python -m website.api.server
```

Leave that terminal running. Open **http://127.0.0.1:8001/explore**.

The page can appear before the model is ready. On first launch, the server
downloads the pinned `Qwen/Qwen2.5-0.5B-Instruct` model revision
`7ae557604adf67be50417f59c2c2f167def9a775` into Hugging Face's local cache. Later
launches prefer that cached snapshot. Wait for the loading indicator to clear.

In a second terminal, from the repository root:

```bash
uv run --locked python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health/ready').read().decode())"
```

Expected: `{"status":"ready"}`. A 503 during loading is normal; persistent
unavailability needs checking the server terminal's traceback.

`make website` is an optional shortcut. Plain `make` starts the extension service,
which is a different application on port 8000.

## 5. Try the controls

To check continuation, select **Continue** and enter `I pushed the door open and`.
The response should contain newly generated text after those words, rather than
a rewrite of the input. Start with all features off, then enable steering for a
controlled comparison. The Continue preset uses the passage as the start of the
assistant response; Run details records this format. Generated continuations
can introduce new content and are not guaranteed to preserve a particular plot.

For a rewritten passage followed by new text, choose **Rewrite & continue**.
The response contains the rewrite, a paragraph break, and its continuation.
Both stages use the selected features and share the output budget. Start with
features off to establish a baseline. A token-limited first stage is returned
as partial text; increase the output budget if needed.

In the spider-web mixer, drag a feature point or focus it and use arrow keys.
The centre is −2, the middle ring is 0, and the edge is +2. **Layer controls**
opens the precise sliders and saved-layer details. Feature checkboxes still
enable/disable steering, and each feature keeps its own layer settings.

1. Enter: `hey can you send me the report before noon?` A response should stream
   automatically. The initial setting is Formality, mean pooling, layer 11/+0.5.
2. In Single layer mode, click layer 7. The Formality chip should change to L7,
   replacing its previous layer.
3. Check **Detoxification**, leaving Formality checked. There should now be two
   feature chips and two active points in the left-hand **Feature mix** block.
   Open **Layer controls** for the precise sliders.
   **Fluency** is also available: enable it to combine all three features, or
   disable the others to inspect fluency alone. Its layer selection, pooling and
   strength remain independent. Test both pooling options and several layers;
   the colours measure held-out pair ordering, not generated response quality.
4. Choose **Edit layers for → Detoxification**, then click layer 11. Formality
   should retain L7. Change either point or precise slider; the other strength should stay
   unchanged. Coloured points on the spider-web axes are draggable; release should
   submit the final value immediately.
5. Change pooling for the edited feature. Switch the editing selector back and
   confirm the other feature retained its pooling and layers.
6. Try Multi-layer mode for one feature: click another layer and check **Enable
   layer**. Its earlier layers should remain listed. Switching that feature back
   to Single layer removes its extra selections.
7. Use **Clear layers** for an unsteered baseline. The task instructions still
   apply. Use **Reset** to restore the initial Formality setup.
8. Select **Summarize** and paste a paragraph. Under **Instructions & limits**,
   edit the system instruction or budgets and press **Apply**. Run details should
   report the applied task, instruction and budgets. No system instruction is
   also available as a task option.

Changing a slider does not guarantee different wording. Vectors are experimental;
strong/many interventions can change meaning or produce repetition. Layer colours
show held-out activation separation, not measured response quality.

## 6. Automated checks

No running server or model weights are needed for the standard Python checks
(one optional tokenizer test is skipped if its snapshot is absent):

```bash
uv run --locked python -m pytest tests/website_api tests/lab -q
```

Optional JavaScript unit tests require Node.js 22 or newer. No npm install:

```bash
cd website/frontend
node --test
cd ../..
```

For the actual-model API smoke check, leave the server running and use a second
terminal:

```bash
uv run --locked python research/steering_experimentation/verify_multifeature_api.py --output multifeature-smoke.local.json
```

Expected: `checks: passed` for baseline, shared-layer features, independent-layer
features and baseline-after-steering. The report records resolved settings and
outputs. It is an integration/isolation check, not a quality evaluation.

Optional browser QA needs the running server, Node.js 22+, and Chrome:

```bash
node website/frontend/tests/browser-smoke.mjs
```

On macOS, the default Chrome location is detected by the script's configured
default path. On Linux set the executable explicitly, for example:

```bash
CHROME_PATH=/usr/bin/google-chrome node website/frontend/tests/browser-smoke.mjs
```

Windows PowerShell:

```powershell
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node website/frontend/tests/browser-smoke.mjs
```

The script prints the temporary screenshot directory and checks real generation,
feature controls, native spider-web dragging, scheduling, cache behaviour,
prompt settings and responsive layouts. `WEBSITE_URL` overrides its server URL.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `uv` not found | Install uv and reopen the terminal; confirm `uv --version` succeeds. |
| Catalog/preflight error | Confirm the PR branch, repository root and all five `.pt` files. Restore matching files; do not mix artifacts from different branches. |
| First startup fails downloading Qwen | Check the server traceback, network/proxy and free disk space. A fresh machine needs network access for the pinned public model. |
| CPU inference is slow | Start with short inputs and a 64/128-token output limit. Raise budgets gradually. |
| Input exceeds token budget | Increase Input budget up to 4,096 or shorten input/instructions. The budget includes chat formatting and instructions; text is not silently truncated. |
| Output limit reached | Increase Output limit up to 512. Review partial output rather than assuming it is complete. |
| Port 8001 already in use | Stop the earlier server with Ctrl+C, or use the alternate-port command below. |
| Old UI, disabled controls or 422 errors after updating | Stop the server, restart from the updated checkout, then refresh the browser. On macOS, Cmd+Shift+R forces a refresh. |
| CUDA requested but unavailable | The locked Linux/Windows environment uses CPU PyTorch. Use CPU for this quickstart. |

Force CPU in macOS/Linux:

```bash
SECONDTHOUGHT_WEBSITE_DEVICE=cpu uv run --locked python -m website.api.server
```

PowerShell equivalent:

```powershell
$env:SECONDTHOUGHT_WEBSITE_DEVICE = 'cpu'
uv run --locked python -m website.api.server
```

For an alternate port:

```bash
uv run --locked python -m uvicorn website.api.server:app --host 127.0.0.1 --port 8002 --workers 1
```

Open `http://127.0.0.1:8002/explore` and pass
`--url http://127.0.0.1:8002` to the API smoke script. Use one worker per model
instance. This quickstart binds locally; it is not a public deployment guide.
