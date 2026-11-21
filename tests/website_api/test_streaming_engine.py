from contextlib import nullcontext
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
    service.observed_generate_options = []

    class Model:
        def generate(self, input_ids, **kwargs):
            service.observed_generate_options.append(kwargs)
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

@pytest.mark.parametrize("fail", [False, True])
def test_explore_multilayer_hooks_and_cleanup(fail):
    from types import MethodType
    from website.api.layers import ExploreRewriter
    service, observed = tiny_service(fail=fail)
    service.layer_vectors = {0: torch.tensor([1., 0.]), 1: torch.tensor([0., 1.])}
    service.layer_bounds = {0: (-2,2), 1: (-2,2)}
    service._layer_steering_context = MethodType(ExploreRewriter._layer_steering_context, service)
    def run():
        return service.stream_rewrite("draft", 0.5, 0, on_text=lambda text: None,
                                      cancelled=Event(), layer_strengths={0: -0.5, 1: 1.2})
    if fail:
        with pytest.raises(RuntimeError):
            run()
    else:
        run()
    assert torch.allclose(observed[0], torch.tensor([[[-0.5, 1.2]]]))
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    assert not service._generation_lock.locked()
    with pytest.raises(ValueError):
        with service._layer_steering_context({0: 1, 9: 1}):
            pass
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    service.layer_bounds[0]=(-0.1,0.1)
    with pytest.raises(ValueError,match='catalog bounds'):
        with service._layer_steering_context({0:0.5}):
            pass


@pytest.mark.parametrize('fail', [False, True])
def test_catalog_feature_overrides_apply_exact_detox_and_formality_shifts(fail):
    from website.api.layers import ExploreRewriter, DEFAULT_MODEL
    from secondthought.lab.catalog import get_catalog
    service = ExploreRewriter.__new__(ExploreRewriter)
    service.catalog = get_catalog()
    service.decoder_layers = torch.nn.ModuleList([torch.nn.Identity() for _ in range(24)])
    vectors = {v.layer_index: v for v in service.catalog.spec.vectors if
               (v.feature_id, v.layer_index, v.pooling) in
               [('detoxification', 11, 'mean'), ('formality', 3, 'mean')] and
               v.behavioral_status == 'experimental'}
    ids = {i:v.id for i,v in vectors.items()}
    strengths = {3: -.4, 11: .7, 4: .3}
    expected = torch.zeros(896)
    for index, strength in strengths.items():
        vector_id = ids.get(index, service.catalog.defaults[(DEFAULT_MODEL,index)])
        expected += service.catalog.vector(vector_id) * strength
    with pytest.raises(RuntimeError) if fail else nullcontext():
        with service._layer_steering_context(strengths, vector_ids=ids):
            hidden = torch.zeros(1, 2, 896)
            for layer in service.decoder_layers:
                hidden = layer(hidden)
            assert torch.allclose(hidden[0,0], expected)
            assert torch.allclose(hidden[0,1], expected)
            if fail:
                raise RuntimeError('forward failed')
    assert all(not layer._forward_hooks for layer in service.decoder_layers)
    with pytest.raises(ValueError, match='match its layer'):
        with service._layer_steering_context({3:.5}, vector_ids={3:ids[11]}):
            pass
    assert all(not layer._forward_hooks for layer in service.decoder_layers)


def test_request_output_budget_is_local_and_context_overflow_is_rejected():
    service, _ = tiny_service()
    service.stream_rewrite('draft',0,0,on_text=lambda text:None,cancelled=Event(),max_new_tokens=256)
    assert service.observed_generate_options[-1]['max_new_tokens'] == 256
    assert service.max_new_tokens == 64
    service.stream_rewrite('draft',0,0,on_text=lambda text:None,cancelled=Event())
    assert service.observed_generate_options[-1]['max_new_tokens'] == 64
    service.model.config = SimpleNamespace(max_position_embeddings=100)
    with pytest.raises(ValueError,match='context window'):
        service.stream_rewrite('draft',0,0,on_text=lambda text:None,cancelled=Event(),max_new_tokens=256)
    assert all(not layer._forward_hooks for layer in service.decoder_layers)


def test_actual_qwen_template_preserves_custom_prompt_and_omits_system_when_requested():
    from pathlib import Path
    from transformers import AutoTokenizer
    snapshot = Path.home()/'.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots/7ae557604adf67be50417f59c2c2f167def9a775'
    if not (snapshot/'tokenizer_config.json').exists():
        pytest.skip('Optional local Qwen tokenizer verification requires the cached snapshot')
    tokenizer = AutoTokenizer.from_pretrained(snapshot,local_files_only=True)
    service = SteeredQwenRewriter.__new__(SteeredQwenRewriter)
    service.tokenizer, service.device = tokenizer, 'cpu'
    custom = service._encode_prompt('Source text',system_prompt='Summarize without new facts.')
    rendered = tokenizer.decode(custom['input_ids'][0])
    assert 'Summarize without new facts.' in rendered
    assert "Rewrite the user's sentence" not in rendered
    bare = service._encode_prompt('What is 2+2?',system_prompt=None)
    rendered = tokenizer.decode(bare['input_ids'][0])
    assert rendered.startswith('<|im_start|>user\n')
    assert '<|im_start|>system' not in rendered
    assert 'You are Qwen' not in rendered


def test_continuation_prefill_is_in_open_assistant_turn_and_counts_toward_prompt_budget():
    from pathlib import Path
    from transformers import AutoTokenizer
    from secondthought.steering_rewriter import CONTINUATION_USER_INSTRUCTION
    snapshot = Path.home()/'.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots/7ae557604adf67be50417f59c2c2f167def9a775'
    if not (snapshot/'tokenizer_config.json').exists():
        pytest.skip('Requires the optional cached Qwen tokenizer')
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    service = SteeredQwenRewriter.__new__(SteeredQwenRewriter)
    service.tokenizer, service.device = tokenizer, 'cpu'
    source = 'I pushed the door open and'
    encoded = service._encode_prompt(source, system_prompt='Continue the passage.',
                                     user_instruction=CONTINUATION_USER_INSTRUCTION)
    rendered = tokenizer.decode(encoded['input_ids'][0])
    assert rendered.endswith('<|im_start|>assistant\n' + source)
    assert source not in rendered.split('<|im_start|>assistant\n')[0]
    assert CONTINUATION_USER_INSTRUCTION in rendered
    # All prefilled source tokens are input tokens, excluded by generation's
    # normal input-length slicing from both returned and streamed responses.
    short = service._encode_prompt('I', system_prompt='Continue the passage.',
                                   user_instruction=CONTINUATION_USER_INSTRUCTION)
    assert encoded['input_ids'].shape[1] > short['input_ids'].shape[1]
