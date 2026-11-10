from __future__ import annotations

import torch

from secondthought.app import (
    OUTPUT_VARIANTS,
    alpha_guidance,
    beta_guidance,
    create_app,
    output_toolbar,
)
from secondthought.steering_rewriter import (
    BASE_REWRITE_PROMPT,
    STEERING_VARIANTS,
    make_steering_hook,
)


class FakeRewriter:
    model_id = "test/model"

    def rewrite_all(
        self,
        message: str,
        alpha: float,
        beta: float,
    ) -> dict[str, str]:
        responses = {
            "combined_steering": (
                f"Combined: {message} (alpha={alpha:+.1f}, beta={beta:+.1f})"
            ),
        }
        return responses


def test_steering_hook_adds_scaled_vector_and_preserves_tuple_tail() -> None:
    residual = torch.zeros((1, 2, 3))
    cached_state = object()
    hook = make_steering_hook(torch.tensor([1.0, 2.0, 3.0]), strength=0.5)

    modified, returned_cache = hook(None, (), (residual, cached_state))

    expected = torch.tensor([[[0.5, 1.0, 1.5], [0.5, 1.0, 1.5]]])
    assert torch.equal(modified, expected)
    assert returned_cache is cached_state


def test_guidance_marks_both_unsteered_baselines_and_risk_regions() -> None:
    assert "Formality off" in alpha_guidance(0)
    assert "Experimental region" in alpha_guidance(2)
    assert "Detox off" in beta_guidance(0)
    assert "Experimental region" in beta_guidance(2)


def test_toolbar_reports_both_independent_parameters() -> None:
    toolbar = output_toolbar(alpha=1.0, beta=-0.5)
    assert "α +1.0" in toolbar
    assert "β -0.5" in toolbar


def test_single_variant_combines_notebook_candidates_with_neutral_prompt() -> None:
    assert [variant.key for variant in STEERING_VARIANTS] == ["combined_steering"]
    assert "Layers 11 + 22" in STEERING_VARIANTS[0].title
    assert BASE_REWRITE_PROMPT == (
        "Rewrite the user's sentence while preserving its meaning. "
        "Return only the rewritten sentence."
    )


def test_gradio_generate_passes_both_strengths_and_returns_plain_text() -> None:
    demo = create_app(FakeRewriter())
    callbacks = [
        fn for fn in demo.fns.values()
        if getattr(fn.fn, "__name__", "") == "generate"
    ]
    assert len(callbacks) == 2  # Button and source textbox submit.
    for callback in callbacks:
        assert len(callback.outputs) == 1
        assert callback.fn("hello", 1.0, 1.5) == (
            "Combined: hello (alpha=+1.0, beta=+1.5)"
        )
    for fn in demo.fns.values():
        if getattr(fn.fn, "__name__", "") == "<lambda>":
            assert len(fn.fn()) == len(fn.outputs) == 7
    demo.close()


def test_app_builds_without_loading_a_real_model() -> None:
    demo = create_app(FakeRewriter())

    assert demo.title == "SecondThought Steering Lab"
    assert len(STEERING_VARIANTS) == 1
    assert [variant.key for variant in OUTPUT_VARIANTS] == [
        "combined_steering",
    ]
    demo.close()
