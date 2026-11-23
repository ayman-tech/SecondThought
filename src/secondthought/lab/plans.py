"""Immutable, deterministic intervention plans resolved from a checked catalog."""
import hashlib
import json
from functools import cached_property
from typing import Literal

from .catalog import Catalog, FrozenSpec
from .interventions import Intervention

MAX_INTERVENTIONS = 256


class ResolvedIntervention(Intervention):
    feature_id: str
    layer_index: int
    pooling: str
    site: str
    scale: str
    artifact_id: str
    artifact_sha256: str
    candidate: str


class InterventionPlan(FrozenSpec):
    model_id: str
    model_revision: str
    catalog_version: str
    adapter: str
    composition: Literal['weighted_sum'] = 'weighted_sum'
    token_scope: Literal['all_tokens'] = 'all_tokens'
    interventions: tuple[ResolvedIntervention, ...]

    @cached_property
    def plan_id(self):
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    def public(self):
        return dict(plan_id=self.plan_id, **self.model_dump())


def resolve_plan(catalog: Catalog, model_id: str, interventions) -> InterventionPlan:
    model = catalog.models.get(model_id)
    if model is None:
        raise ValueError('Unknown catalog model')
    if len(interventions) > MAX_INTERVENTIONS:
        raise ValueError(f'At most {MAX_INTERVENTIONS} interventions are supported')
    seen, resolved = set(), []
    for entry in sorted(interventions, key=lambda i:i.vector_id):
        if entry.vector_id in seen:
            raise ValueError('Duplicate vector ID; combine its strengths into one intervention')
        seen.add(entry.vector_id)
        vector = catalog.vectors.get(entry.vector_id)
        if vector is None or vector.model_id != model_id:
            raise ValueError('Vector is unknown or incompatible with the selected model')
        if vector.site != 'decoder_block_output':
            raise ValueError('Unsupported intervention site')
        if not vector.strength_min <= entry.strength <= vector.strength_max:
            raise ValueError('Intervention strength is outside its catalog bounds')
        catalog.vector(vector.id)  # Availability is required even at strength zero.
        artifact = catalog.artifacts[vector.artifact_id]
        resolved.append(ResolvedIntervention(vector_id=vector.id, strength=entry.strength,
            feature_id=vector.feature_id, layer_index=vector.layer_index,
            pooling=vector.pooling, site=vector.site, scale=vector.scale,
            artifact_id=artifact.id, artifact_sha256=artifact.sha256, candidate=vector.candidate))
    return InterventionPlan(model_id=model.id, model_revision=model.revision,
        catalog_version=catalog.version, adapter=model.adapter, interventions=tuple(resolved))
