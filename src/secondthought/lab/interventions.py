"""Request-scoped weighted vector composition and cleanup-safe hooks."""
from contextlib import ExitStack, contextmanager

import torch
from pydantic import Field

from secondthought.steering_rewriter import make_steering_hook
from .catalog import Catalog, FrozenSpec


class Intervention(FrozenSpec):
    vector_id: str = Field(min_length=1,max_length=300)
    strength: float = Field(strict=True)


def compile_interventions(catalog: Catalog, model_id: str, interventions):
    if model_id not in catalog.models:
        raise ValueError('Unknown catalog model')
    seen, grouped = set(), {}
    for intervention in sorted(interventions, key=lambda entry: entry.vector_id):
        vector = catalog.vectors.get(intervention.vector_id)
        if vector is None or vector.model_id != model_id:
            raise ValueError('Intervention vector is unknown or incompatible with the model')
        if vector.id in seen:
            raise ValueError('Duplicate intervention vector')
        seen.add(vector.id)
        if not vector.strength_min <= intervention.strength <= vector.strength_max:
            raise ValueError('Intervention strength is outside its catalog bounds')
        effective = catalog.vector(vector.id)  # Validate availability even at zero.
        if intervention.strength:
            grouped.setdefault(vector.layer_index, []).append(effective * intervention.strength)
    compiled = {index: vectors[0] if len(vectors) == 1 else torch.stack(vectors).sum(0)
                for index, vectors in grouped.items()}
    if any(not torch.isfinite(shift).all() for shift in compiled.values()):
        raise ValueError('Combined intervention contains nonfinite values')
    return compiled


@contextmanager
def steering_context(layers, compiled):
    with ExitStack() as stack:
        for index, shift in sorted(compiled.items()):
            if not 0 <= index < len(layers):
                raise ValueError('Compiled intervention has an invalid decoder index')
            handle = layers[index].register_forward_hook(make_steering_hook(shift, 1.0))
            stack.callback(handle.remove)
        yield
