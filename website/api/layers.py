"""Explicit map of promoted, non-shuffled vectors available to the Explore lab."""
from contextlib import ExitStack, contextmanager

from secondthought.steering_rewriter import (
    SteeredQwenRewriter, DEFAULT_FORMALITY_DIRECTION_PATH, DEFAULT_DETOX_DIRECTION_PATH,
    load_direction_artifact, make_steering_hook,
)

LAYER_VECTORS = {
    0: dict(concept="Detoxification", candidate="best_mean", pooling="mean", normalized=True),
    4: dict(concept="Formality", candidate="alternative_layer4_final", pooling="final token", normalized=False),
    11: dict(concept="Formality", candidate="negative_layer11_mean", pooling="mean", normalized=False),
    21: dict(concept="Formality", candidate="primary_layer21_mean", pooling="mean", normalized=False),
    22: dict(concept="Detoxification", candidate="best_final", pooling="final token", normalized=True),
}


def layer_manifest():
    return [dict(index=index, available=index in LAYER_VECTORS, **LAYER_VECTORS.get(index, {}))
            for index in range(24)]


class ExploreRewriter(SteeredQwenRewriter):
    """Website-only layer experiments; the extension's default service is unchanged."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        artifacts = {
            "Formality": load_direction_artifact(DEFAULT_FORMALITY_DIRECTION_PATH),
            "Detoxification": load_direction_artifact(DEFAULT_DETOX_DIRECTION_PATH),
        }
        self.layer_vectors = {}
        for index, spec in LAYER_VECTORS.items():
            artifact = artifacts[spec["concept"]]
            candidate = artifact["candidates"][spec["candidate"]]
            vector = artifact["raw_directions"][spec["candidate"]].float()
            if int(candidate["layer_index"]) != index or not 0 <= index < len(self.decoder_layers):
                raise ValueError("Steering manifest layer does not match its artifact")
            if vector.ndim != 1 or vector.numel() != self.model.config.hidden_size:
                raise ValueError("Steering vector dimensions do not match the model")
            if spec["normalized"]:
                vector = vector / vector.norm().clamp_min(1e-12)
            self.layer_vectors[index] = vector.cpu()

    @contextmanager
    def _layer_steering_context(self, strengths):
        with ExitStack() as stack:
            for index, strength in sorted(strengths.items()):
                if index not in self.layer_vectors or not -2 <= strength <= 2:
                    raise ValueError("Unsupported layer or steering strength")
                if strength:
                    handle = self.decoder_layers[index].register_forward_hook(
                        make_steering_hook(self.layer_vectors[index], strength)
                    )
                    stack.callback(handle.remove)
            yield
