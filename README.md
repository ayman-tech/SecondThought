# Second Thought

Online and workplace communication can often become rude, aggressive, or toxic, which can lead to misunderstandings and conflict. The goal of this project is to build a Transformer-based language model that rewrites toxic or angry messages into respectful, neutral language while preserving the original meaning and intent.

## Try the saved model

Install the local inference and notebook dependencies from `pyproject.toml`:

```bash
uv sync
```

This creates `.venv` using the project's Python 3.12 setting. Open [t5-inference.ipynb](t5-inference.ipynb) in VS Code and choose **Select Kernel → Python Environments → .venv/bin/python**. Run the cells in order, then type a sentence when the last cell prompts you. Rerun that cell for each new sentence; no retraining is needed.

Set `MODEL_DIR` to your extracted model folder, such as `./epoch5`. The notebook can also extract a matching ZIP whose top-level folder has the same name. Inference uses the local CPU and local model files; no NVIDIA GPU is required. Review outputs for neutral tone and preservation of meaning.

`pyproject.toml` and `uv.lock` manage local dependencies. The training notebook keeps its separate Colab installation cell.

## Fine-tune T5-small

Open [t5-ft.ipynb](t5-ft.ipynb) in [Google Colab](https://colab.research.google.com/) using **File → Upload notebook**, or Colab's GitHub tab. Select **Runtime → Change runtime type → GPU** and run the cells in order. Use a fresh Python 3.10+ runtime; the first cell installs pinned dependencies alongside Colab's existing PyTorch.

The notebook fine-tunes `google-t5/t5-small` on [ParaDetox](https://huggingface.co/datasets/s-nlp/paradetox), mapping toxic comments to neutral rewrites. It explains data preparation, tokenization, training, evaluation, and inference. Repeated toxic inputs stay in the same split to prevent leakage.

- Start with `SMOKE_TEST = True` in the configuration cell to check five training steps, evaluation, saving, reloading, and generation on a small subset.
- For full training, set `SMOKE_TEST = False` and rerun from the configuration cell onward. Defaults are 3 epochs, learning rate `3e-4`, batch size 8, and gradient accumulation 2, using full precision.
- If GPU memory is insufficient, lower `BATCH_SIZE` to 4 or 2. Training time depends on the assigned GPU. CPU execution is supported but much slower.
- The best checkpoint is selected by validation loss. Test loss and input/reference/output examples are shown afterward; loss alone does not establish toxicity reduction or meaning preservation.

The final model and tokenizer are exported to `./t5-small-paradetox`; the last cell downloads a ZIP. Smoke runs use separate folders ending in `-smoke` and `-smoke-checkpoints`. Download your model before the Colab session ends. Training checkpoints live separately in `./t5-small-paradetox-checkpoints`.

The notebook includes a reusable `detoxify(text)` function and instructions for loading the exported model later. Training runs locally within your Colab runtime; the notebook does not publish the model to Hugging Face or enable external experiment tracking.
