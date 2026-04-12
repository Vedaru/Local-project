"""
Memory module — MemPalace-style memory system.

Public API:
  HumanMemoryEngine — the main memory manager (store / retrieve / stats / close)
"""

from .core import HumanMemoryEngine

__all__ = ["HumanMemoryEngine"]
