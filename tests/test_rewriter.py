from types import SimpleNamespace

import pytest

from secondthought.rewriter import OpenAIRewriter


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="response-1",
            output_text="Please fix the timeout before merging.",
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=9,
            ),
        )


def test_rewrite_uses_external_prompt_and_configured_model(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Rewrite professionally.", encoding="utf-8")
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    rewriter = OpenAIRewriter(
        model="test-model",
        prompt_path=prompt,
        max_output_tokens=100,
        client=client,
    )

    result = rewriter.rewrite("Fix this stupid timeout.")

    assert result.rewritten_text == "Please fix the timeout before merging."
    assert result.latency_ms >= 0
    assert result.model_info == "test-model"
    assert result.timestamp_utc.endswith("+00:00")
    assert responses.kwargs == {
        "model": "test-model",
        "instructions": "Rewrite professionally.",
        "input": "Fix this stupid timeout.",
        "max_output_tokens": 100,
        "store": False,
    }


def test_rewrite_rejects_empty_message(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Rewrite professionally.", encoding="utf-8")
    rewriter = OpenAIRewriter(
        model="test-model",
        prompt_path=prompt,
        client=SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        rewriter.rewrite("   ")
