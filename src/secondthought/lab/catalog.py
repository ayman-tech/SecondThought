"""Versioned steering catalogs with content-checked, model-compatible vectors.

Catalog construction never loads an LM or a dataset. A broken artifact disables
its vectors without hiding the remaining catalog or exposing local file paths.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import torch
from pydantic import BaseModel, ConfigDict, Field, model_validator

ARTIFACT_ROOT = Path(__file__).resolve().parents[3] / "artifacts"
DEFAULT_MANIFEST = ARTIFACT_ROOT / "catalog/qwen2_5_0_5b.json"


class FrozenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ModelSpec(FrozenSpec):
    id: str
    repository: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    layer_count: int = Field(gt=0)
    hidden_size: int = Field(gt=0)
    adapter: Literal["qwen2_decoder_output_v1"]


class FeatureSpec(FrozenSpec):
    id: str
    label: str
    positive_direction: str


class ArtifactSpec(FrozenSpec):
    id: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str
    feature_id: str
    model_revision: str | None
    format: Literal["legacy", "all_layers_v1"]


class VectorSpec(FrozenSpec):
    id: str
    model_id: str
    feature_id: str
    artifact_id: str
    candidate: str
    layer_index: int = Field(ge=0)
    pooling: Literal["mean", "final_token"]
    site: Literal["decoder_block_output"] = "decoder_block_output"
    scale: Literal["raw", "unit_l2"]
    raw_norm: float = Field(gt=0)
    strength_min: float = -2
    strength_max: float = 2
    strength_step: float = Field(default=0.1, gt=0)
    default_strength: float = 0.5
    behavioral_status: Literal["experimental", "legacy_reference"] = "experimental"
    strength_range_status: Literal["uncalibrated", "legacy_range"] = "uncalibrated"

    @model_validator(mode="after")
    def strength_bounds(self):
        if not self.strength_min <= self.default_strength <= self.strength_max:
            raise ValueError("Default strength must be within its bounds")
        return self


class LayerDefault(FrozenSpec):
    model_id: str
    layer_index: int = Field(ge=0)
    vector_id: str


class CatalogSpec(FrozenSpec):
    schema_version: Literal[1]
    id: str
    models: tuple[ModelSpec, ...]
    features: tuple[FeatureSpec, ...]
    artifacts: tuple[ArtifactSpec, ...]
    vectors: tuple[VectorSpec, ...]
    layer_defaults: tuple[LayerDefault, ...]


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Catalog:
    def __init__(self, spec: CatalogSpec, artifact_root: Path):
        self.spec = spec
        self.root = artifact_root.resolve()
        self.models = self._indexed(spec.models)
        self.features = self._indexed(spec.features)
        self.artifacts = self._indexed(spec.artifacts)
        self.vectors = self._indexed(spec.vectors)
        self.defaults = {}
        self.issues = {}
        self._loaded = {}
        self._tensors = {}
        for artifact in spec.artifacts:
            model = self.models.get(artifact.model_id)
            if (model is None or artifact.feature_id not in self.features or
                    (artifact.model_revision is not None and artifact.model_revision != model.revision)):
                raise ValueError("Artifact references an unknown or incompatible model revision")
            self._load_artifact(artifact, model)
        for vector in spec.vectors:
            self._validate_vector(vector)
        for default in spec.layer_defaults:
            vector = self.vectors.get(default.vector_id)
            key = (default.model_id, default.layer_index)
            if key in self.defaults or vector is None or (vector.model_id, vector.layer_index) != key:
                raise ValueError("Invalid or duplicate layer default")
            self.defaults[key] = default.vector_id
        canonical = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        self.version = hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _indexed(entries):
        result = {entry.id: entry for entry in entries}
        if len(result) != len(entries):
            raise ValueError("Duplicate catalog identifier")
        return result

    @classmethod
    def load(cls, manifest=None, artifact_root=None):
        manifest=manifest or os.getenv('SECONDTHOUGHT_LAB_CATALOG') or DEFAULT_MANIFEST
        artifact_root=artifact_root or os.getenv('SECONDTHOUGHT_LAB_ARTIFACT_ROOT') or ARTIFACT_ROOT
        return cls(CatalogSpec.model_validate_json(Path(manifest).read_text()), Path(artifact_root))

    def _load_artifact(self, artifact, model):
        path = (self.root / artifact.path).resolve()
        if Path(artifact.path).is_absolute() or not path.is_relative_to(self.root):
            raise ValueError("Artifact paths must remain inside the artifact root")
        try:
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != artifact.sha256:
                self.issues[artifact.id] = "checksum_mismatch"
                return
            data = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
            if data.get("model_id") != model.repository:
                raise ValueError("model_mismatch")
            if artifact.format == "all_layers_v1":
                if (data.get("format_version") != 1 or data.get("feature") != artifact.feature_id or
                    data.get("model_revision") != model.revision or
                    data.get("tokenizer_revision") != model.revision or
                    data.get("site") != "decoder_block_output" or
                    data.get("layer_count") != model.layer_count or
                    data.get("hidden_size") != model.hidden_size):
                    raise ValueError("provenance_mismatch")
            if not isinstance(data.get("candidates"), dict) or not isinstance(data.get("raw_directions"), dict):
                raise ValueError("invalid_artifact_structure")
            self._loaded[artifact.id] = data
        except FileNotFoundError:
            self.issues[artifact.id] = "missing_artifact"
        except Exception:
            self.issues[artifact.id] = "invalid_artifact"

    def _validate_vector(self, vector):
        artifact = self.artifacts.get(vector.artifact_id)
        model = self.models.get(vector.model_id)
        if (artifact is None or model is None or artifact.model_id != vector.model_id or
                artifact.feature_id != vector.feature_id or
                vector.feature_id not in self.features or vector.layer_index >= model.layer_count):
            raise ValueError("Vector references incompatible catalog entries")
        data = self._loaded.get(vector.artifact_id)
        if data is None:
            self.issues[vector.id] = self.issues[vector.artifact_id]
            return
        try:
            candidate = data["candidates"][vector.candidate]
            raw = data["raw_directions"][vector.candidate]
            if (candidate.get("layer_index") != vector.layer_index or candidate.get("pooling") != vector.pooling or
                    candidate.get("is_control", False) or
                    candidate.get("site", "decoder_block_output") != vector.site):
                raise ValueError("candidate_mismatch")
            if not isinstance(raw, torch.Tensor) or not raw.is_floating_point() or raw.shape != (model.hidden_size,):
                raise ValueError("invalid_shape")
            raw = raw.float()
            norm = float(raw.norm())
            if not torch.isfinite(raw).all() or not math.isfinite(norm) or norm <= 0:
                raise ValueError("nonfinite_or_zero_vector")
            if not math.isclose(norm, vector.raw_norm, rel_tol=1e-5, abs_tol=1e-6):
                raise ValueError("norm_mismatch")
            self._tensors[vector.id] = raw / norm if vector.scale == "unit_l2" else raw
        except Exception:
            self.issues[vector.id] = "invalid_vector"

    def vector(self, vector_id: str) -> torch.Tensor:
        if vector_id not in self._tensors:
            raise ValueError(f"Vector is unavailable: {vector_id}")
        return self._tensors[vector_id].clone()

    def layer_manifest(self, model_id: str):
        model = self.models[model_id]
        result = []
        for index in range(model.layer_count):
            vector_id = self.defaults.get((model_id, index))
            vector = self.vectors.get(vector_id)
            available = vector_id in self._tensors
            entry = dict(index=index, available=available)
            if vector is not None:
                entry.update(vector_id=vector.id, concept=self.features[vector.feature_id].label,
                    candidate=vector.candidate, pooling=vector.pooling.replace('_', ' '),
                    normalized=vector.scale == "unit_l2", behavioral_status=vector.behavioral_status)
                if not available:
                    entry["unavailable_reason"] = self.issues.get(vector_id, "not_available")
            result.append(entry)
        return result

    def public(self):
        from .evidence import layer_evidence_profiles
        artifacts = []
        for artifact in self.spec.artifacts:
            entry = artifact.model_dump(exclude={"path"})
            entry.update(available=artifact.id in self._loaded,
                         unavailable_reason=self.issues.get(artifact.id))
            data = self._loaded.get(artifact.id, {})
            entry['provenance'] = data.get('provenance', {
                'extraction_model_revision': None, 'extraction_precision': None,
                'extraction_pairs': data.get('extraction_pairs'), 'seed': data.get('seed'),
                'note': 'Legacy extraction snapshot/precision not established; original vector preserved.',
            })
            artifacts.append(entry)
        vectors = []
        for vector in self.spec.vectors:
            entry = vector.model_dump()
            entry.update(available=vector.id in self._tensors, unavailable_reason=self.issues.get(vector.id))
            data = self._loaded.get(vector.artifact_id, {})
            candidate = data.get('candidates', {}).get(vector.candidate, {})
            entry['heldout'] = {key: value for key, value in candidate.items() if key.startswith('heldout_')}
            vectors.append(entry)
        return dict(schema_version=1, catalog_id=self.spec.id, catalog_version=self.version,
            models=[m.model_dump() for m in self.spec.models],
            features=[f.model_dump() for f in self.spec.features], artifacts=artifacts, vectors=vectors,
            layer_defaults=[d.model_dump() for d in self.spec.layer_defaults],
            layer_evidence_profiles={m.id:layer_evidence_profiles(self,m.id) for m in self.spec.models},
            note='Available vectors are experimental. Held-out projection separation is not a guarantee of generation quality.')


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog.load()
