"""Capture pooled decoder-block outputs without retaining full hidden states.

Extraction deliberately uses the same forward-hook boundary as inference, not
the model's hidden-state tuple (whose final entry can include normalization).
"""

from contextlib import ExitStack
from typing import Sequence

import torch

POOLINGS = ("mean", "final_token")
SITE = "decoder_block_output"


def pooled_outputs(hidden: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    if hidden.ndim != 3 or mask.shape != hidden.shape[:2]:
        raise ValueError("Hidden states and attention mask have incompatible shapes")
    valid = mask.bool()
    if not valid.any(dim=1).all():
        raise ValueError("Every sequence must contain a non-padding token")
    states = hidden.float()
    mean = (states * valid.unsqueeze(-1)).sum(1) / valid.sum(1).unsqueeze(-1)
    positions = torch.arange(mask.shape[1], device=mask.device).expand_as(mask)
    last = positions.masked_fill(~valid, -1).max(1).values
    final = states[torch.arange(len(mask), device=mask.device), last]
    return torch.stack((mean, final))


def capture_representations(forward, layers: Sequence, inputs: dict) -> torch.Tensor:
    """Return [pooling, sequence, decoder index, width], with hooks always removed."""
    captured = {}

    def hook(index):
        def capture(_module, _inputs, output):
            if index in captured:
                raise ValueError("A decoder block executed more than once during extraction")
            hidden = output[0] if isinstance(output, tuple) else output
            captured[index] = pooled_outputs(hidden, inputs["attention_mask"])
        return capture

    with ExitStack() as stack, torch.inference_mode():
        for index, layer in enumerate(layers):
            handle = layer.register_forward_hook(hook(index))
            stack.callback(handle.remove)
        forward(**inputs, use_cache=False, return_dict=True)
        if set(captured) != set(range(len(layers))):
            raise ValueError("Not every decoder block was captured")
        return torch.stack([captured[i] for i in range(len(layers))], dim=2)
