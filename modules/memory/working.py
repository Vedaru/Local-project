"""Working Memory — short-term buffer of recent interactions.

Mimics human working memory: ~7 items capacity, FIFO eviction.
All operations are thread-safe.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Optional


@dataclass
class WorkingMemoryTurn:
    user_text: str = ""
    ai_text: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkingMemory:
    """Thread-safe short-term memory buffer."""

    def __init__(self, capacity: int = 7, embedding_fn=None):
        self.capacity = max(3, capacity)
        self._buffer: deque[WorkingMemoryTurn] = deque(maxlen=self.capacity)
        self._lock = RLock()

    @property
    def size(self) -> int:
        return len(self._buffer)

    def add_turn(self, user_text: str, ai_text: str, metadata: Optional[dict] = None):
        with self._lock:
            turn = WorkingMemoryTurn(
                user_text=user_text,
                ai_text=ai_text,
                timestamp=time.time(),
                metadata=metadata or {},
            )
            self._buffer.append(turn)

    def get_recent(self, n: int = 5) -> list[WorkingMemoryTurn]:
        with self._lock:
            items = list(self._buffer)
        return items[-n:] if n > 0 else []

    def get_context_string(self) -> str:
        turns = self.get_recent()
        parts = [f"用户: {t.user_text}\nAI: {t.ai_text}" for t in turns]
        return "\n\n".join(parts)

    def clear(self):
        with self._lock:
            self._buffer.clear()

    def search(self, query: str, n_results: int = 3) -> list[WorkingMemoryTurn]:
        query_lower = (query or "").lower().strip()
        if not query_lower:
            return self.get_recent(n_results)

        scored: list[tuple[float, WorkingMemoryTurn]] = []
        with self._lock:
            for t in self._buffer:
                score = 0.0
                if query_lower in t.user_text.lower():
                    score += 0.8
                elif query_lower in t.ai_text.lower():
                    score += 0.4
                words = query_lower.split()
                for w in words:
                    if len(w) > 1 and w in t.user_text.lower():
                        score += 0.15
                if score > 0:
                    scored.append((score, t))

        scored.sort(reverse=True, key=lambda x: x[0])
        return [t for _, t in scored[:n_results]]
