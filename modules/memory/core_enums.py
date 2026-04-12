"""Memory tier and item types for the human memory system."""


from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryTier(str, Enum):
    WORKING = "working"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    ENGRAM = "engram"


@dataclass
class MemoryItem:
    id: str = ""
    content: str = ""
    source_tier: MemoryTier = MemoryTier.WORKING
    confidence: float = 0.5
    relevance: float = 0.0
    composite_score: float = 0.0
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
