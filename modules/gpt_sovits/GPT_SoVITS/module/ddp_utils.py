"""Minimal DDP utilities stub for inference (non-distributed)."""

import torch


class SyncFunction(torch.autograd.Function):
    """Identity pass-through when not using distributed training."""

    @staticmethod
    def forward(ctx, tensor):
        return tensor

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output
