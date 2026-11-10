"""Compare the app backend against the original notebook generation functions.

Run: uv run python research/steering_experimentation/verify_qwen_integration.py --device cpu
Only function definitions are loaded from notebooks; extraction cells are not run.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path

import torch

from secondthought.app import create_app
from secondthought.steering_rewriter import (
    BASE_REWRITE_PROMPT,
    DEFAULT_DETOX_DIRECTION_PATH,
    DEFAULT_FORMALITY_DIRECTION_PATH,
    PROJECT_ROOT,
    SteeredQwenRewriter,
    load_direction_artifact,
)


def notebook_functions(path: Path, names: set[str], namespace: dict) -> dict:
    notebook = json.loads(path.read_text())
    definitions = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                definitions.append(node)
    assert {node.name for node in definitions} == names
    module = ast.Module(body=definitions, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def verify(device: str | None) -> dict:
    service = SteeredQwenRewriter(device=device)
    root = PROJECT_ROOT / "research" / "steering_experimentation"
    common = dict(
        torch=torch, contextmanager=contextmanager, nullcontext=nullcontext,
        model=service.model, tokenizer=service.tokenizer, device=service.device,
        decoder_layers=service.decoder_layers,
    )
    formal = load_direction_artifact(DEFAULT_FORMALITY_DIRECTION_PATH)
    detox = load_direction_artifact(DEFAULT_DETOX_DIRECTION_PATH)
    formal_ns = notebook_functions(root / "activation_steering.ipynb", {
        "make_steering_hook", "steering_context", "generate_rewrite",
    }, dict(common, CANDIDATES=formal["candidates"], raw_directions=formal["raw_directions"]))
    detox_ns = notebook_functions(root / "paradetox_activation_steering.ipynb", {
        "steering_vector", "make_steering_hook", "steering_context", "encode_prompt", "generate",
    }, dict(common, candidates=detox["candidates"], raw_directions=detox["raw_directions"],
            STEERING_VECTOR_MODE="unit_normalized", MAX_NEW_TOKENS=64))
    prompt = "Rewrite the user's sentence while preserving its meaning. Return only the rewritten sentence."
    assert BASE_REWRITE_PROMPT == prompt

    # Compare actual generated token IDs, not just postprocessed strings.
    original_generate = service.model.generate
    generated = []
    def record_generate(*args, **kwargs):
        ids = original_generate(*args, **kwargs)
        generated.append(ids.detach().cpu())
        return ids
    service.model.generate = record_generate
    cases = []
    try:
        for text, concept in [
            ("its really hard when u want to know what happened", "formality"),
            ("send me the fucking report by 3 PM", "formality"),
            ("if people didn 't buy this shit they wouldn 't be doing it .", "toxicity"),
        ]:
            for strength in (-2.0, 0.0, 0.5, 1.0, 2.0):
                alpha, beta = (strength, 0.0) if concept == "formality" else (0.0, strength)
                actual = service.rewrite_all(text, alpha, beta)["combined_steering"]
                app_ids = generated[-1]
                if concept == "formality":
                    expected = formal_ns["generate_rewrite"](text, prompt, "negative_layer11_mean", strength)
                else:
                    expected = detox_ns["generate"](text, prompt, "best_final", strength)
                assert actual == expected and torch.equal(app_ids, generated[-1]), (text, strength)
                cases.append(dict(text=text, alpha=alpha, beta=beta, output=actual, notebook_token_match=True))
                print(f"alpha={alpha:+.1f} beta={beta:+.1f}: {actual}", flush=True)

        text = "send me the fucking report by 3 PM"
        actual = service.rewrite_all(text, 0.5, 1.0)["combined_steering"]
        app_ids = generated[-1]
        with formal_ns["steering_context"]("negative_layer11_mean", 0.5):
            expected = detox_ns["generate"](text, prompt, "best_final", 1.0)
        assert actual == expected and torch.equal(app_ids, generated[-1])
        cases.append(dict(text=text, alpha=0.5, beta=1.0, output=actual, notebook_token_match=True))
    finally:
        service.model.generate = original_generate

    # Measure the exact additive shift on the real decoder outputs.
    audit = {}
    handles = []
    def capture(key, field):
        def hook(_module, _inputs, output):
            residual = output[0] if isinstance(output, tuple) else output
            audit.setdefault(key, {})[field] = residual[:, -1, :].detach().float().cpu()
        return hook
    layers = {k: service.decoder_layers[int(v["layer_index"])] for k, v in service.candidates.items()}
    initial_hooks = {k: len(layer._forward_hooks) for k, layer in layers.items()}
    try:
        for key, layer in layers.items():
            handles.append(layer.register_forward_hook(capture(key, "before")))
        with service._mixed_steering_context(0.5, 1.0):
            for key, layer in layers.items():
                handles.append(layer.register_forward_hook(capture(key, "after")))
            with torch.inference_mode():
                shifted_logits = service.model(**service._encode_prompt(text)).logits[:, -1, :].float().cpu()
    finally:
        for handle in handles:
            handle.remove()
    assert {k: len(layer._forward_hooks) for k, layer in layers.items()} == initial_hooks
    with torch.inference_mode():
        baseline_logits = service.model(**service._encode_prompt(text)).logits[:, -1, :].float().cpu()
    shifts = {}
    for key, strength in (("formality", 0.5), ("toxicity", 1.0)):
        observed = audit[key]["after"] - audit[key]["before"]
        expected = strength * service.directions[key].float().cpu()
        error = float((observed - expected).abs().max())
        assert error < (0.05 if service.device.type != "cpu" else 1e-4)
        shifts[key] = dict(layer=service.candidates[key]["layer_index"],
                           vector_norm=float(service.directions[key].norm()),
                           observed_shift_norm=float(observed.norm()), max_error=error)
    logit_change = float((shifted_logits - baseline_logits).abs().max())
    assert logit_change > 0

    # Exercise Gradio's registered callback with the real backend.
    demo = create_app(service)
    callbacks = [fn for fn in demo.fns.values() if getattr(fn.fn, "__name__", "") == "generate"]
    for callback in callbacks:
        assert callback.fn(text, 0.5, 1.0) == actual
    demo.close()
    return dict(model=service.model_id, device=str(service.device), dtype=str(service.model.dtype),
                prompt=prompt, shifts=shifts, max_next_token_logit_change=logit_change,
                gradio_callback_matches=True, cases=cases,
                artifacts={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (DEFAULT_FORMALITY_DIRECTION_PATH, DEFAULT_DETOX_DIRECTION_PATH)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=None)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "research/outputs/qwen_notebook_parity.json")
    args = parser.parse_args()
    report = verify(args.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Notebook parity, activation shifts, hook cleanup, and Gradio checks passed.")
    print("Report:", args.output)
