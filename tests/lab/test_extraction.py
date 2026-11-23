import pytest
import torch

from secondthought.lab.extraction import capture_representations, pooled_outputs


def test_pooling_ignores_padding_and_uses_last_non_padding_token():
    hidden = torch.tensor([[[2., 4.], [6., 8.], [900., 900.]],
                           [[900., 900.], [2., 4.], [6., 8.]]])
    pooled = pooled_outputs(hidden, torch.tensor([[1, 1, 0], [0, 1, 1]]))
    assert torch.equal(pooled[0], torch.tensor([[4., 6.], [4., 6.]]))
    assert torch.equal(pooled[1], torch.tensor([[6., 8.], [6., 8.]]))
    with pytest.raises(ValueError, match='non-padding'):
        pooled_outputs(hidden, torch.zeros(2, 3))


@pytest.mark.parametrize('fail', [False, True])
def test_capture_uses_actual_block_output_before_final_norm_and_cleans_hooks(fail):
    class Block(torch.nn.Module):
        def forward(self, hidden):
            return hidden + 1
    layers = torch.nn.ModuleList([Block(), Block()])
    def forward(input_ids, attention_mask, **kwargs):
        hidden = input_ids.float().unsqueeze(-1).repeat(1, 1, 2)
        for layer in layers:
            hidden = layer(hidden)
        if fail:
            raise RuntimeError('forward failure')
        return hidden * 100  # A final model-level normalization/transform.
    inputs = dict(input_ids=torch.tensor([[1, 3, 0]]), attention_mask=torch.tensor([[1, 1, 0]]))
    if fail:
        with pytest.raises(RuntimeError, match='forward failure'):
            capture_representations(forward, layers, inputs)
    else:
        captured = capture_representations(forward, layers, inputs)
        assert captured.shape == (2, 1, 2, 2)
        assert torch.equal(captured[0, 0, 1], torch.tensor([4., 4.]))
        assert torch.equal(captured[1, 0, 1], torch.tensor([5., 5.]))
    assert all(not layer._forward_hooks for layer in layers)
