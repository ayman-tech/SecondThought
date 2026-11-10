from threading import Event, Lock
from time import monotonic
from types import SimpleNamespace

import pytest
import torch

from secondthought.steering_rewriter import (
    GenerationCancelled, SteeredQwenRewriter, _StopGeneration,
)


def tiny_service(*, fail=False, cancel_during=None):
    """Exercise the real generation/hook context without downloading weights."""
    service = SteeredQwenRewriter.__new__(SteeredQwenRewriter)
    service._generation_lock = Lock()
    service.max_new_tokens = 64
    service.decoder_layers = torch.nn.ModuleList([torch.nn.Identity(), torch.nn.Identity()])
    service.candidates = {"formality": {"layer_index": 0}, "toxicity": {"layer_index": 1}}
    service.directions = {"formality": torch.tensor([1., 0.]), "toxicity": torch.tensor([0., 1.])}
    service.tokenizer = SimpleNamespace(
        eos_token_id=3, pad_token_id=3, decode=lambda *args, **kwargs: "Clean text.",
    )
    service._encode_prompt = lambda text: {"input_ids": torch.zeros((1, len(text)), dtype=torch.long)}
    observed = []

    class Model:
        def generate(self, input_ids, **kwargs):
            hidden = torch.zeros((1, 1, 2))
            for layer in service.decoder_layers:
                hidden = layer(hidden)
            observed.append(hidden)
            if fail:
                raise RuntimeError("failure in forward pass")
            if cancel_during:
                cancel_during.set()
            streamer = kwargs.get("streamer")
            if streamer:
                streamer.on_finalized_text("Clean text.", stream_end=True)
            return torch.cat([input_ids, torch.tensor([[2, 3]])], dim=1)
    service.model = Model()
    return service, observed


def test_streaming_adds_correct_vectors_at_their_own_layers_and_cleans_up():
    service, observed = tiny_service()
    chunks = []
    result = service.stream_rewrite("draft", 0.5, 1, on_text=chunks.append, cancelled=Event())
    assert torch.equal(observed[0], torch.tensor([[[0.5, 1.]]]))
    assert result.text == "Clean text." and result.finish_reason == "stop"
    assert "".join(chunks) == result.text
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    assert not service._generation_lock.locked()


def test_forward_failure_always_removes_hooks_and_releases_lock():
    service, _ = tiny_service(fail=True)
    with pytest.raises(RuntimeError, match="failure in forward"):
        service.stream_rewrite("draft", 1, 0, on_text=lambda text: None, cancelled=Event())
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    assert not service._generation_lock.locked()


def test_cancelled_output_is_not_returned_as_a_completed_rewrite():
    event = Event()
    service, _ = tiny_service(cancel_during=event)
    with pytest.raises(GenerationCancelled):
        service.stream_rewrite("draft", 1, 0, on_text=lambda text: None, cancelled=event)
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    assert not service._generation_lock.locked()


def test_oversized_prompt_is_rejected_before_generation_without_truncation():
    service, observed = tiny_service()
    with pytest.raises(ValueError, match="shorten"):
        service.stream_rewrite("long draft", 0.5, 0, on_text=lambda text: None,
                               cancelled=Event(), max_input_tokens=3)
    assert not observed
    assert not service._generation_lock.locked()


def test_cancellation_and_timeout_stopping_criteria():
    event = Event()
    criterion = _StopGeneration(event, monotonic() + 60)
    assert not criterion(None, None)
    event.set()
    assert criterion(None, None)
    assert _StopGeneration(Event(), monotonic() - 1)(None, None)
