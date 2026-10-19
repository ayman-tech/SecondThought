"""Feature-agnostic activation steering for encoder-decoder rewrite models."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterator, Mapping

import torch
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from .steering_rewriter import BASE_REWRITE_PROMPT, make_steering_hook, select_device


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_PATH = (
    PROJECT_ROOT
    / "steering_experimentation"
    / "artifacts"
    / "flan_t5_small_feature_directions.pt"
)


@dataclass(frozen=True)
class EncoderDecoderSteeringVariant:
    key: str
    title: str
    detail: str


ENCODER_DECODER_STEERING_VARIANTS = (
    EncoderDecoderSteeringVariant(
        key="t5_combined_steering",
        title="Combined steering · FLAN-T5",
        detail="ENCODER–DECODER · α FORMALITY · β DETOXIFICATION",
    ),
)


@dataclass(frozen=True)
class FeatureIntervention:
    """Runtime description of one independently controllable feature."""

    key: str
    site: str
    layer_index: int
    direction: torch.Tensor
    coefficient_scale: float = 1.0


def _resolve_model_source(model_id: str) -> str:
    try:
        return snapshot_download(repo_id=model_id, local_files_only=True)
    except LocalEntryNotFoundError:
        return model_id


def load_feature_artifact(path: str | Path) -> dict:
    artifact_path = Path(path).expanduser().resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(
            f"Encoder-decoder steering artifact not found: {artifact_path}. "
            "Run steering_experimentation/t5_feature_steering.ipynb first."
        )
    artifact = torch.load(artifact_path, map_location="cpu", weights_only=True)
    required = {"format_version", "model_id", "intervention_site", "features"}
    missing = required - set(artifact)
    if missing:
        raise ValueError(f"Feature artifact is missing fields: {sorted(missing)}")
    supported_sites = {"decoder_blocks", "encoder_and_decoder_blocks"}
    if artifact["intervention_site"] not in supported_sites:
        raise ValueError(
            "This runtime does not support artifact intervention site "
            f"{artifact['intervention_site']!r}"
        )
    return artifact


class EncoderDecoderFeatureSteerer:
    """Apply any registered feature directions during one seq2seq generation."""

    def __init__(
        self,
        artifact_path: str | Path = DEFAULT_ARTIFACT_PATH,
        *,
        device: str | torch.device | None = None,
        max_input_tokens: int = 192,
        max_new_tokens: int = 80,
        num_beams: int = 4,
        default_candidate: str = "decoder",
    ) -> None:
        artifact = load_feature_artifact(artifact_path)
        self.model_id = str(artifact["model_id"])
        self.device = torch.device(device) if device is not None else select_device()
        self.max_input_tokens = max_input_tokens
        self.max_new_tokens = max_new_tokens
        self.num_beams = num_beams
        self.default_candidate = default_candidate
        self._generation_lock = Lock()

        self.feature_candidates: dict[str, dict[str, FeatureIntervention]] = {}
        for feature_key, metadata in artifact["features"].items():
            candidate_metadata = metadata.get("candidates")
            if candidate_metadata is None:
                candidate_metadata = {
                    "decoder": {
                        **metadata,
                        "site": "decoder_blocks",
                    }
                }
            self.feature_candidates[feature_key] = {}
            for candidate_key, candidate in candidate_metadata.items():
                self.feature_candidates[feature_key][candidate_key] = FeatureIntervention(
                    key=feature_key,
                    site=str(candidate["site"]),
                    layer_index=int(candidate["layer_index"]),
                    direction=candidate["direction"].float().cpu(),
                    coefficient_scale=float(candidate.get("coefficient_scale", 1.0)),
                )

        self.features = self._select_features(default_candidate)

        model_source = _resolve_model_source(self.model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(model_source)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_source)
        self.model = self.model.to(self.device)
        self.model.eval()
        self.encoder_blocks = self.model.encoder.block
        self.decoder_blocks = self.model.decoder.block

        hidden_size = int(self.model.config.d_model)
        for candidates in self.feature_candidates.values():
            for feature in candidates.values():
                blocks = self._blocks_for_site(feature.site)
                if not 0 <= feature.layer_index < len(blocks):
                    raise ValueError(
                        f"Feature {feature.key!r} uses invalid {feature.site} layer "
                        f"{feature.layer_index}"
                    )
                if (
                    feature.direction.ndim != 1
                    or feature.direction.shape[0] != hidden_size
                ):
                    raise ValueError(
                        f"Feature {feature.key!r} has direction shape "
                        f"{tuple(feature.direction.shape)}; expected ({hidden_size},)"
                    )

    def _select_features(
        self, candidate_set: str
    ) -> dict[str, FeatureIntervention]:
        missing = [
            key
            for key, candidates in self.feature_candidates.items()
            if candidate_set not in candidates
        ]
        if missing:
            raise ValueError(
                f"Candidate set {candidate_set!r} is unavailable for features: {missing}"
            )
        return {
            key: candidates[candidate_set]
            for key, candidates in self.feature_candidates.items()
        }

    def _blocks_for_site(self, site: str):
        if site == "encoder_blocks":
            return self.encoder_blocks
        if site == "decoder_blocks":
            return self.decoder_blocks
        raise ValueError(f"Unsupported intervention site: {site!r}")

    @contextmanager
    def steering_context(
        self,
        controls: Mapping[str, float],
        candidate_set: str | None = None,
    ) -> Iterator[None]:
        features = (
            self.features
            if candidate_set is None
            else self._select_features(candidate_set)
        )
        unknown = set(controls) - set(features)
        if unknown:
            raise ValueError(f"Unknown steering features: {sorted(unknown)}")

        with ExitStack() as stack:
            for feature_key, coefficient in controls.items():
                coefficient = float(coefficient)
                if coefficient == 0:
                    continue
                feature = features[feature_key]
                strength = coefficient * feature.coefficient_scale
                blocks = self._blocks_for_site(feature.site)
                handle = blocks[feature.layer_index].register_forward_hook(
                    make_steering_hook(feature.direction, strength)
                )
                stack.callback(handle.remove)
            yield

    def rewrite(
        self,
        message: str,
        controls: Mapping[str, float],
        candidate_set: str | None = None,
    ) -> str:
        message = message.strip()
        if not message:
            raise ValueError("Enter a message to rewrite.")
        for feature_key, coefficient in controls.items():
            if not -2.0 <= float(coefficient) <= 2.0:
                raise ValueError(
                    f"Control {feature_key!r} must be between -2.0 and +2.0."
                )

        prompt = f"{BASE_REWRITE_PROMPT}\n\nMessage:\n{message}"
        model_inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=False,
        )
        input_length = int(model_inputs["input_ids"].shape[1])
        if input_length > self.max_input_tokens:
            raise ValueError(
                f"The input is {input_length} FLAN-T5 tokens; the steering model "
                f"supports at most {self.max_input_tokens}."
            )
        model_inputs = model_inputs.to(self.device)

        with self._generation_lock:
            with self.steering_context(
                controls, candidate_set=candidate_set
            ), torch.inference_mode():
                output_ids = self.model.generate(
                    **model_inputs,
                    max_new_tokens=self.max_new_tokens,
                    num_beams=self.num_beams,
                    do_sample=False,
                )
        rewritten = self.tokenizer.decode(
            output_ids[0], skip_special_tokens=True
        ).strip()
        if not rewritten:
            raise RuntimeError("The encoder-decoder model returned an empty rewrite")
        return rewritten


class T5FeatureSteeringRewriter:
    """App adapter for the initial formality and detoxification feature registry."""

    def __init__(
        self,
        steerer: EncoderDecoderFeatureSteerer | None = None,
    ) -> None:
        self.steerer = steerer or EncoderDecoderFeatureSteerer()
        required = {"formality", "detoxification"}
        missing = required - set(self.steerer.features)
        if missing:
            raise ValueError(
                f"The T5 feature artifact is missing app controls: {sorted(missing)}"
            )

    def rewrite_all(
        self,
        message: str,
        alpha: float,
        beta: float,
        formality_enabled: bool = True,
        detoxification_enabled: bool = True,
        candidate_set: str = "decoder",
    ) -> dict[str, str]:
        controls = {
            "formality": float(alpha) if formality_enabled else 0.0,
            "detoxification": float(beta) if detoxification_enabled else 0.0,
        }
        return {
            "t5_combined_steering": self.steerer.rewrite(
                message,
                controls,
                candidate_set=candidate_set,
            )
        }
