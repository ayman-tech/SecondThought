"""Local inference for the two fine-tuned T5 rewrite models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
import zipfile

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"


@dataclass(frozen=True)
class FineTunedVariant:
    """A user-visible response card backed by a fine-tuned T5 model."""

    key: str
    title: str
    detail: str
    model_directory: str
    archive_name: str
    prefix: str


FINE_TUNED_VARIANTS = (
    FineTunedVariant(
        key="detox_t5",
        title="Detox fine-tune",
        detail="T5-small fine-tuned on ParaDetox.",
        model_directory="t5-small-paradetox",
        archive_name="detox-t5.zip",
        prefix="detoxify: ",
    ),
    FineTunedVariant(
        key="formalize_t5",
        title="Formality fine-tune",
        detail="T5-small fine-tuned for formal rewriting.",
        model_directory="formalize-t5",
        archive_name="formalize-t5.zip",
        prefix="formalize: ",
    ),
)

REQUIRED_MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer_config.json",
    "tokenizer.json",
)


def _extract_model_archive(archive_path: Path, model_path: Path) -> None:
    """Extract one known model folder while rejecting paths outside it."""

    extraction_root = model_path.parent.resolve()
    expected_root = model_path.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            destination = (extraction_root / member.filename).resolve()
            if not destination.is_relative_to(expected_root):
                raise ValueError(
                    f"Unexpected path {member.filename!r} in {archive_path.name}"
                )
        archive.extractall(extraction_root)


def resolve_model_directory(variant: FineTunedVariant) -> Path:
    """Return a validated model directory, extracting its local ZIP if needed."""

    model_path = (MODELS_ROOT / variant.model_directory).resolve()
    if not model_path.exists():
        archive_path = (MODELS_ROOT / variant.archive_name).resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(
                f"Cannot find {model_path} or {archive_path}. "
                "Place the fine-tuned model archive in the models directory."
            )
        _extract_model_archive(archive_path, model_path)

    missing = [name for name in REQUIRED_MODEL_FILES if not (model_path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Incomplete model folder {model_path}: missing {missing}"
        )
    return model_path


class FineTunedT5Rewriter:
    """Load both local T5 models and generate their rewrites for one input."""

    def __init__(
        self,
        *,
        device: str | torch.device = "cpu",
        max_input_tokens: int = 128,
        max_new_tokens: int = 128,
        num_beams: int = 4,
    ) -> None:
        self.device = torch.device(device)
        self.max_input_tokens = max_input_tokens
        self.max_new_tokens = max_new_tokens
        self.num_beams = num_beams
        self._generation_lock = Lock()
        self._models: dict[str, tuple[object, object]] = {}

        for variant in FINE_TUNED_VARIANTS:
            model_path = resolve_model_directory(variant)
            tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                local_files_only=True,
            )
            model = AutoModelForSeq2SeqLM.from_pretrained(
                model_path,
                local_files_only=True,
            )
            model = model.to(self.device)
            model.eval()
            self._models[variant.key] = (tokenizer, model)

    def _generate(self, message: str, variant: FineTunedVariant) -> str:
        tokenizer, model = self._models[variant.key]
        model_inputs = tokenizer(
            variant.prefix + message,
            return_tensors="pt",
            truncation=False,
        )
        input_length = int(model_inputs["input_ids"].shape[1])
        if input_length > self.max_input_tokens:
            raise ValueError(
                f"The input is {input_length} T5 tokens; the fine-tuned models "
                f"support at most {self.max_input_tokens}. Try a shorter sentence."
            )

        model_inputs = model_inputs.to(self.device)
        with torch.inference_mode():
            output_ids = model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens,
                num_beams=self.num_beams,
                do_sample=False,
            )
        rewritten = tokenizer.decode(
            output_ids[0],
            skip_special_tokens=True,
        ).strip()
        if not rewritten:
            raise RuntimeError(f"{variant.title} returned an empty rewrite")
        return rewritten

    def rewrite_all(self, message: str) -> dict[str, str]:
        """Generate one alpha-independent rewrite from each fine-tuned model."""

        message = message.strip()
        if not message:
            raise ValueError("Enter a message to rewrite.")

        # Keep model generation serialized if Gradio later enables concurrency.
        with self._generation_lock:
            return {
                variant.key: self._generate(message, variant)
                for variant in FINE_TUNED_VARIANTS
            }
