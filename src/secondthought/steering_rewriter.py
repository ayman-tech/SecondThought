"""Local Qwen rewriting with formality and detoxification steering."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterator

import torch
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from transformers import AutoModelForCausalLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIRECTORY = PROJECT_ROOT / "steering_experimentation" / "artifacts"
DEFAULT_FORMALITY_DIRECTION_PATH = (
    ARTIFACT_DIRECTORY / "qwen2_5_0_5b_gyafc_formality_directions.pt"
)
DEFAULT_DETOX_DIRECTION_PATH = (
    ARTIFACT_DIRECTORY / "qwen2_5_0_5b_paradetox_directions.pt"
)

BASE_REWRITE_PROMPT = (
    "Rewrite the message with minimal wording changes. Preserve its meaning, "
    "facts, names, numbers, deadlines, requested actions, and intent. Do not add "
    "explanations, greetings, or new information. Return only the rewritten message."
)


@dataclass(frozen=True)
class SteeringVariant:
    """A user-visible response backed by the two saved concept directions."""

    key: str
    title: str
    detail: str


STEERING_VARIANTS = (
    SteeringVariant(
        key="combined_steering",
        title="Combined steering · Layers 4 + 11",
        detail="α FORMALITY · β DETOXIFICATION",
    ),
)


def select_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def resolve_model_source(model_id: str) -> str:
    """Prefer a local Hugging Face snapshot and download only when absent."""

    try:
        return snapshot_download(repo_id=model_id, local_files_only=True)
    except LocalEntryNotFoundError:
        return model_id


def load_direction_artifact(
    path: str | Path,
    required_candidate: str | None = None,
) -> dict:
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
    if required_candidate is not None:
        if required_candidate not in artifact["candidates"]:
            raise ValueError(
                f"Direction artifact has no candidate {required_candidate!r}"
            )
        if required_candidate not in artifact["raw_directions"]:
            raise ValueError(
                f"Direction artifact has no vector for {required_candidate!r}"
            )
    return artifact


def make_steering_hook(vector: torch.Tensor, strength: float):
    """Return a forward hook that shifts every token representation."""

    def steering_hook(module, module_inputs, module_output):
        del module, module_inputs
        is_tuple = isinstance(module_output, tuple)
        residual = module_output[0] if is_tuple else module_output
        shift = (strength * vector).to(
            device=residual.device,
            dtype=residual.dtype,
        )
        modified = residual + shift.view(1, 1, -1)
        if is_tuple:
            return (modified, *module_output[1:])
        return modified

    return steering_hook


class SteeredQwenRewriter:
    """Generate one Qwen rewrite with simultaneous formality and detox steering."""

    def __init__(
        self,
        formality_direction_path: str | Path = DEFAULT_FORMALITY_DIRECTION_PATH,
        detox_direction_path: str | Path = DEFAULT_DETOX_DIRECTION_PATH,
        *,
        device: str | torch.device | None = None,
        max_new_tokens: int = 64,
    ) -> None:
        artifacts = {
            "formality": load_direction_artifact(
                formality_direction_path,
                required_candidate="alternative_layer4_final",
            ),
            "toxicity": load_direction_artifact(
                detox_direction_path,
                required_candidate="layer11_mean",
            ),
        }
        model_ids = {str(artifact["model_id"]) for artifact in artifacts.values()}
        if len(model_ids) != 1:
            raise ValueError(
                "Formality and toxicity directions must use the same base model; "
                f"found {sorted(model_ids)}"
            )

        self.model_id = model_ids.pop()
        self.device = torch.device(device) if device is not None else select_device()
        self.max_new_tokens = max_new_tokens
        self._generation_lock = Lock()
        formality_key = "alternative_layer4_final"
        detox_key = "layer11_mean"
        self.candidates = {
            "formality": artifacts["formality"]["candidates"][formality_key],
            "toxicity": artifacts["toxicity"]["candidates"][detox_key],
        }

        formality_direction = artifacts["formality"]["raw_directions"][
            formality_key
        ].float()
        detox_direction = artifacts["toxicity"]["raw_directions"][detox_key].float()
        detox_direction = detox_direction / detox_direction.norm().clamp_min(1e-12)
        self.directions = {
            "formality": formality_direction.cpu(),
            # The causal sweep found detoxification on the saved direction's
            # negative side, so positive beta uses the empirically useful sign.
            "toxicity": (-detox_direction).cpu(),
        }

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
        for concept in ("formality", "toxicity"):
            layer_index = int(self.candidates[concept]["layer_index"])
            if not 0 <= layer_index < len(self.decoder_layers):
                raise ValueError(
                    f"Concept {concept!r} uses invalid layer {layer_index}"
                )
            vector = self.directions[concept]
            if vector.ndim != 1 or vector.shape[0] != hidden_size:
                raise ValueError(
                    f"Concept {concept!r} has vector shape {tuple(vector.shape)}; "
                    f"expected ({hidden_size},)"
                )

    @contextmanager
    def _mixed_steering_context(
        self, alpha: float, beta: float
    ) -> Iterator[None]:
        strengths = {"formality": alpha, "toxicity": beta}
        with ExitStack() as stack:
            for concept, strength in strengths.items():
                if strength == 0:
                    continue
                layer_index = int(self.candidates[concept]["layer_index"])
                handle = self.decoder_layers[layer_index].register_forward_hook(
                    make_steering_hook(self.directions[concept], strength)
                )
                stack.callback(handle.remove)
            yield

    def _encode_prompt(self, message: str):
        user_content = f"{BASE_REWRITE_PROMPT}\n\nMessage:\n{message}"
        messages = [
            {"role": "user", "content": user_content},
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def _generate(
        self,
        model_inputs,
        alpha: float,
        beta: float,
    ) -> str:
        with self._mixed_steering_context(alpha, beta), torch.inference_mode():
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

    def rewrite_all(
        self,
        message: str,
        alpha: float,
        beta: float,
        formality_enabled: bool = True,
        detoxification_enabled: bool = True,
    ) -> dict[str, str]:
        """Generate one rewrite with both independently controlled directions."""

        message = message.strip()
        if not message:
            raise ValueError("Enter a message to rewrite.")
        alpha = float(alpha)
        beta = float(beta)
        if not -2.0 <= alpha <= 2.0:
            raise ValueError("Alpha must be between -2.0 and +2.0.")
        if not -2.0 <= beta <= 2.0:
            raise ValueError("Beta must be between -2.0 and +2.0.")

        effective_alpha = alpha if formality_enabled else 0.0
        effective_beta = beta if detoxification_enabled else 0.0

        with self._generation_lock:
            inputs = self._encode_prompt(message)
            return {
                "combined_steering": self._generate(
                    inputs, effective_alpha, effective_beta
                ),
            }
