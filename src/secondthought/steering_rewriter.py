"""Local Qwen rewriting with activation-steering directions."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterator

import torch
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from transformers import AutoModelForCausalLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTION_PATH = (
    PROJECT_ROOT
    / "steering_experimentation"
    / "artifacts"
    / "qwen2_5_0_5b_gyafc_formality_directions.pt"
)


@dataclass(frozen=True)
class SteeringVariant:
    """A user-visible response card backed by one saved direction."""

    key: str
    title: str
    detail: str


STEERING_VARIANTS = (
    SteeringVariant(
        key="alternative_layer4_final",
        title="Response A · Layer 4 steering",
        detail="Direction extracted from each sentence's final-token representation.",
    ),
    SteeringVariant(
        key="negative_layer11_mean",
        title="Response B · Layer 11 steering",
        detail="Direction extracted from each sentence's mean-pooled representation.",
    ),
)

NEUTRAL_REWRITE_PROMPT = (
    "Rewrite the user's sentence while preserving its meaning. "
    "Return only the rewritten sentence."
)


def select_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def resolve_model_source(model_id: str) -> str:
    """Prefer the local Hugging Face snapshot and download only when absent."""

    try:
        return snapshot_download(repo_id=model_id, local_files_only=True)
    except LocalEntryNotFoundError:
        return model_id


def load_direction_artifact(path: str | Path) -> dict:
    artifact_path = Path(path).expanduser().resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(
            f"Steering direction artifact not found: {artifact_path}. "
            "Run the direction-extraction notebook first."
        )

    artifact = torch.load(artifact_path, map_location="cpu", weights_only=True)
    required_fields = {"model_id", "candidates", "raw_directions"}
    missing_fields = required_fields - set(artifact)
    if missing_fields:
        raise ValueError(
            f"Direction artifact is missing fields: {sorted(missing_fields)}"
        )

    for variant in STEERING_VARIANTS:
        if variant.key not in artifact["candidates"]:
            raise ValueError(f"Direction artifact has no candidate {variant.key!r}")
        if variant.key not in artifact["raw_directions"]:
            raise ValueError(f"Direction artifact has no vector for {variant.key!r}")
    return artifact


def make_steering_hook(vector: torch.Tensor, alpha: float):
    """Return a forward hook that shifts every active token representation."""

    def steering_hook(module, module_inputs, module_output):
        del module, module_inputs
        is_tuple = isinstance(module_output, tuple)
        residual = module_output[0] if is_tuple else module_output
        shift = (alpha * vector).to(device=residual.device, dtype=residual.dtype)
        modified = residual + shift.view(1, 1, -1)
        if is_tuple:
            return (modified, *module_output[1:])
        return modified

    return steering_hook


class SteeredQwenRewriter:
    """Load one local model and produce responses from multiple directions."""

    def __init__(
        self,
        direction_path: str | Path = DEFAULT_DIRECTION_PATH,
        *,
        device: str | torch.device | None = None,
        max_new_tokens: int = 64,
    ) -> None:
        artifact = load_direction_artifact(direction_path)
        self.model_id = str(artifact["model_id"])
        self.candidates = artifact["candidates"]
        self.raw_directions = artifact["raw_directions"]
        self.device = torch.device(device) if device is not None else select_device()
        self.max_new_tokens = max_new_tokens
        self._generation_lock = Lock()

        dtype = torch.float16 if self.device.type in {"mps", "cuda"} else torch.float32
        model_source = resolve_model_source(self.model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(model_source)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "right"

        self.model = AutoModelForCausalLM.from_pretrained(model_source, dtype=dtype)
        self.model = self.model.to(self.device)
        self.model.eval()
        self.decoder_layers = self.model.model.layers

        hidden_size = int(self.model.config.hidden_size)
        for variant in STEERING_VARIANTS:
            layer_index = int(self.candidates[variant.key]["layer_index"])
            if not 0 <= layer_index < len(self.decoder_layers):
                raise ValueError(
                    f"Candidate {variant.key!r} uses invalid layer {layer_index}"
                )
            vector = self.raw_directions[variant.key]
            if vector.ndim != 1 or vector.shape[0] != hidden_size:
                raise ValueError(
                    f"Candidate {variant.key!r} has vector shape {tuple(vector.shape)}; "
                    f"expected ({hidden_size},)"
                )

    @contextmanager
    def _steering_context(self, candidate_key: str, alpha: float) -> Iterator[None]:
        layer_index = int(self.candidates[candidate_key]["layer_index"])
        handle = self.decoder_layers[layer_index].register_forward_hook(
            make_steering_hook(self.raw_directions[candidate_key], alpha)
        )
        try:
            yield
        finally:
            handle.remove()

    def _encode_prompt(self, message: str):
        messages = [
            {"role": "system", "content": NEUTRAL_REWRITE_PROMPT},
            {"role": "user", "content": message},
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def _generate(self, model_inputs, candidate_key: str, alpha: float) -> str:
        steering = (
            self._steering_context(candidate_key, alpha)
            if alpha != 0
            else nullcontext()
        )
        with steering, torch.inference_mode():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        prompt_length = model_inputs["input_ids"].shape[1]
        new_ids = generated_ids[0, prompt_length:]
        rewritten = self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        if not rewritten:
            raise RuntimeError("The model returned an empty rewrite")
        return rewritten

    def rewrite_all(self, message: str, alpha: float) -> dict[str, str]:
        """Generate one deterministic rewrite for every configured card."""

        message = message.strip()
        if not message:
            raise ValueError("Enter a message to rewrite.")
        alpha = float(alpha)
        if not -2.0 <= alpha <= 2.0:
            raise ValueError("Alpha must be between -2.0 and +2.0.")

        # Forward hooks mutate shared model behavior, so the complete comparison
        # is serialized even if the Gradio server later accepts concurrent users.
        with self._generation_lock:
            model_inputs = self._encode_prompt(message)
            return {
                variant.key: self._generate(model_inputs, variant.key, alpha)
                for variant in STEERING_VARIANTS
            }
