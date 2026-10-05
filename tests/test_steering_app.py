from __future__ import annotations

import torch

from secondthought.app import alpha_guidance, create_app
from secondthought.steering_rewriter import STEERING_VARIANTS, make_steering_hook


class FakeRewriter:
    model_id = "test/model"

    def rewrite_all(self, message: str, alpha: float) -> dict[str, str]:
        return {
            variant.key: f"{variant.title}: {message} ({alpha:+.1f})"
            for variant in STEERING_VARIANTS
        }


def test_steering_hook_adds_scaled_vector_and_preserves_tuple_tail() -> None:
    residual = torch.zeros((1, 2, 3))
    cached_state = object()
    hook = make_steering_hook(torch.tensor([1.0, 2.0, 3.0]), alpha=0.5)

    modified, returned_cache = hook(None, (), (residual, cached_state))

    expected = torch.tensor([[[0.5, 1.0, 1.5], [0.5, 1.0, 1.5]]])
    assert torch.equal(modified, expected)
    assert returned_cache is cached_state


def test_alpha_guidance_marks_baseline_and_drift_region() -> None:
    assert "Unsteered rewrite baseline" in alpha_guidance(0)
    assert "Experimental region" in alpha_guidance(2)


def test_app_builds_without_loading_a_real_model() -> None:
    demo = create_app(FakeRewriter())

    assert demo.title == "SecondThought Steering Lab"
    assert len(STEERING_VARIANTS) == 2
