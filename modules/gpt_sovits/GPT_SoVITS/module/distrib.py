"""Minimal distrib stubs for inference (non-distributed)."""

import typing as tp
import torch


def is_distributed():
    return torch.distributed.is_initialized()


def broadcast_tensors(tensors: tp.Iterable[torch.Tensor], src: int = 0):
    if not is_distributed():
        return
    tensors = list(tensors)
    for tensor in tensors:
        torch.distributed.broadcast(tensor, src=src)
