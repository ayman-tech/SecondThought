"""Local Qwen rewriting with formality and detoxification steering."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Callable, Iterator

import torch
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from transformers import (
    AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList,
    TextStreamer,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Runtime assets. These are copies promoted from research/steering_experimentation/artifacts/
# (see artifacts/README.md), so the product never depends on the research folder.
ARTIFACT_DIRECTORY = PROJECT_ROOT / "artifacts"
DEFAULT_FORMALITY_DIRECTION_PATH = (
    ARTIFACT_DIRECTORY / "qwen2_5_0_5b_gyafc_formality_directions.pt"
)
DEFAULT_DETOX_DIRECTION_PATH = (
    ARTIFACT_DIRECTORY / "qwen2_5_0_5b_paradetox_directions.pt"
)

BASE_REWRITE_PROMPT = (
    "Rewrite the user's sentence while preserving its meaning. "
    "Return only the rewritten sentence."
)


@dataclass(frozen=True)
class SteeringVariant:
    """A user-visible response backed by the two saved concept directions."""

    key: str
    title: str
    detail: str


@dataclass(frozen=True)
class GenerationResult:
    text: str
    generated_tokens: int
    finish_reason: str


class GenerationCancelled(Exception):
    """A superseded or disconnected request stopped at a decoding boundary."""


class _StopGeneration(StoppingCriteria):
    def __init__(self, cancelled: Event, deadline: float):
        self.cancelled = cancelled
        self.deadline = deadline

    def __call__(self, input_ids, scores, **kwargs):
        return self.cancelled.is_set() or monotonic() >= self.deadline


class _CallbackStreamer(TextStreamer):
    def __init__(self, tokenizer, callback: Callable[[str], None]):
        super().__init__(tokenizer, skip_prompt=True, skip_special_tokens=True)
        self.callback = callback

    def on_finalized_text(self, text: str, stream_end: bool = False):
        if text:
            self.callback(text)


STEERING_VARIANTS = (
    SteeringVariant(
        key="combined_steering",
        title="Combined steering · Layers 11 + 22",
        detail="α FORMALITY · β DETOXIFICATION",
    ),
)


def select_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def resolve_model_source(model_id: str, revision: str | None = None) -> str:
    """Prefer a local Hugging Face snapshot and download only when absent."""

    try:
        return snapshot_download(repo_id=model_id, local_files_only=True,
                                 **({"revision": revision} if revision is not None else {}))
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
        model_revision: str | None = None,
    ) -> None:
        artifacts = {
            "formality": load_direction_artifact(
                formality_direction_path,
                required_candidate="negative_layer11_mean",
            ),
            "toxicity": load_direction_artifact(
                detox_direction_path,
                required_candidate="best_final",
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
        # Match the causal runs reported in the two activation notebooks.
        # The historical "negative" name denotes the original geometry control;
        # the formality notebook subsequently found a visible causal effect here.
        formality_key = "negative_layer11_mean"
        detox_key = "best_final"
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
            "toxicity": detox_direction.cpu(),
        }

        # MPS float16 produced repetition even with no steering (e.g. "hello").
        # Full precision matches the CPU baseline on the supported Mac runtime.
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model_revision = model_revision
        model_source = resolve_model_source(self.model_id, **({"revision": model_revision} if model_revision else {}))
        source_options = {"revision": model_revision} if model_revision and model_source == self.model_id else {}
        self.tokenizer = AutoTokenizer.from_pretrained(model_source, **source_options)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "right"

        self.model = AutoModelForCausalLM.from_pretrained(model_source, dtype=dtype, **source_options)
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

    def _encode_prompt(self, message: str, system_prompt: str | None = BASE_REWRITE_PROMPT):
        messages = [
            {"role": "system", "content": system_prompt or ''},
            {"role": "user", "content": message},
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        if system_prompt is None:
            # Qwen's template inserts a default assistant instruction when the
            # system role is omitted. Render an empty role and strip its exact
            # template-produced prefix so "none" really has no system message.
            empty_system = self.tokenizer.apply_chat_template(
                [messages[0]], tokenize=False, add_generation_prompt=False)
            if not empty_system or not prompt.startswith(empty_system):
                raise ValueError('This chat template cannot omit the system instruction')
            prompt = prompt[len(empty_system):]
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def _generate(
        self,
        model_inputs,
        alpha: float,
        beta: float,
    ) -> str:
        return self._generate_result(model_inputs, alpha, beta).text

    def _generate_result(
        self, model_inputs, alpha: float, beta: float, *,
        streamer=None, stopping_criteria=None, layer_strengths=None, layer_vector_ids=None,
        max_new_tokens=None, interventions=None,
    ) -> GenerationResult:
        extra = {}
        if streamer is not None:
            extra["streamer"] = streamer
        if stopping_criteria is not None:
            extra["stopping_criteria"] = stopping_criteria
        if interventions is not None:
            context = self._intervention_context(interventions)
        else:
            context = (self._mixed_steering_context(alpha, beta) if layer_strengths is None
                       else self._layer_steering_context(layer_strengths, **(
                           {"vector_ids": layer_vector_ids} if layer_vector_ids else {})))
        with context, torch.inference_mode():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens if max_new_tokens is None else max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                **extra,
            )

        prompt_length = model_inputs["input_ids"].shape[1]
        new_ids = generated_ids[0, prompt_length:]
        rewritten = self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        if not rewritten:
            raise RuntimeError("The model returned an empty rewrite")
        eos = self.tokenizer.eos_token_id
        finished = bool(len(new_ids) and int(new_ids[-1]) == eos)
        return GenerationResult(
            text=rewritten, generated_tokens=len(new_ids),
            finish_reason="stop" if finished else "length",
        )

    def stream_rewrite(
        self, message: str, alpha: float, beta: float, *,
        on_text: Callable[[str], None], cancelled: Event,
        max_input_tokens: int = 384, timeout_seconds: float = 25.0,
        layer_strengths: dict[int, float] | None = None,
        layer_vector_ids: dict[int, str] | None = None,
        system_prompt: str | None = BASE_REWRITE_PROMPT,
        max_new_tokens: int | None = None,
        interventions=None,
    ) -> GenerationResult:
        """Stream the same deterministic generation with cooperative cancellation.

        The lock covers encoding, all forward hooks, and the entire generation.
        Partial/cancelled outputs are never returned as successful results.
        """
        if not message.strip():
            raise ValueError("Enter a message to rewrite.")
        alpha, beta = float(alpha), float(beta)
        if interventions is not None and (layer_strengths is not None or layer_vector_ids is not None or alpha or beta):
            raise ValueError('Explicit interventions cannot be combined with legacy steering controls')
        if layer_vector_ids and layer_strengths is None:
            raise ValueError('Vector choices require explicit layer strengths')
        if not -2 <= alpha <= 2 or not -2 <= beta <= 2:
            raise ValueError("Steering strengths must be between -2 and +2.")
        with self._generation_lock:
            if cancelled.is_set():
                raise GenerationCancelled()
            inputs = (self._encode_prompt(message) if system_prompt == BASE_REWRITE_PROMPT
                      else self._encode_prompt(message, system_prompt=system_prompt))
            output_budget = self.max_new_tokens if max_new_tokens is None else max_new_tokens
            if isinstance(output_budget, bool) or not isinstance(output_budget, int) or output_budget <= 0:
                raise ValueError('Output token budget must be a positive integer')
            context_limit = getattr(getattr(self.model, 'config', None), 'max_position_embeddings', None)
            if context_limit and inputs['input_ids'].shape[1] + output_budget > context_limit:
                raise ValueError('Input and output budgets exceed the model context window')
            if inputs["input_ids"].shape[1] > max_input_tokens:
                raise ValueError(
                    f"Please shorten the input or instructions: the full prompt exceeds {max_input_tokens} tokens."
                )
            deadline = monotonic() + timeout_seconds
            try:
                result = self._generate_result(
                    inputs, alpha, beta,
                    streamer=_CallbackStreamer(self.tokenizer, on_text),
                    stopping_criteria=StoppingCriteriaList([_StopGeneration(cancelled, deadline)]),
                    **({"layer_strengths": layer_strengths} if layer_strengths is not None else {}),
                    **({"layer_vector_ids": layer_vector_ids} if layer_vector_ids else {}),
                    **({"max_new_tokens": max_new_tokens} if max_new_tokens is not None else {}),
                    **({"interventions": interventions} if interventions is not None else {}),
                )
            except Exception:
                # A stop before any decoded text can produce an empty-output
                # error. Preserve the cancellation/timeout outcome in that case.
                if cancelled.is_set():
                    raise GenerationCancelled() from None
                if monotonic() >= deadline:
                    raise TimeoutError("Generation timed out. Please shorten the draft and retry.") from None
                raise
            if cancelled.is_set():
                raise GenerationCancelled()
            if monotonic() >= deadline:
                raise TimeoutError("Generation timed out. Please shorten the draft and retry.")
            return result

    def rewrite_all(
        self,
        message: str,
        alpha: float,
        beta: float,
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

        with self._generation_lock:
            inputs = self._encode_prompt(message)
            return {
                "combined_steering": self._generate(inputs, alpha, beta),
            }
