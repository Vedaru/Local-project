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

from .text_search import tokenize_for_search


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

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    @classmethod
    def _matches_user(cls, metadata: Optional[dict[str, Any]], user_id: Optional[str]) -> bool:
        uid = cls._normalize_user_id(user_id)
        if not uid:
            return True
        turn_uid = cls._normalize_user_id((metadata or {}).get("user_id"))
        return turn_uid == uid

    def add_turn(
        self,
        user_text: str,
        ai_text: str,
        metadata: Optional[dict] = None,
        timestamp: Optional[float] = None,
    ):
        with self._lock:
            ts = time.time() if timestamp is None else float(timestamp)
            turn = WorkingMemoryTurn(
                user_text=user_text,
                ai_text=ai_text,
                timestamp=ts,
                metadata=metadata or {},
            )
            self._buffer.append(turn)

    def get_recent(self, n: int = 5, user_id: Optional[str] = None) -> list[WorkingMemoryTurn]:
        with self._lock:
            if not user_id:
                items = list(self._buffer)
            else:
                items = [t for t in self._buffer if self._matches_user(t.metadata, user_id)]
        return items[-n:] if n > 0 else []

    def get_context_string(self, user_id: Optional[str] = None) -> str:
        turns = self.get_recent(user_id=user_id)
        parts = [f"用户: {t.user_text}\nAI: {t.ai_text}" for t in turns]
        return "\n\n".join(parts)

    def clear(self):
        with self._lock:
            self._buffer.clear()

    @staticmethod
    def _compact_text(text: str) -> str:
        return "".join((text or "").lower().split())

    def search(
        self,
        query: str,
        n_results: int = 3,
        user_id: Optional[str] = None,
        allow_recent_fallback: bool = True,
    ) -> list[WorkingMemoryTurn]:
        top_k = max(1, int(n_results or 1))
        query_text = (query or "").strip()
        if not query_text:
            return self.get_recent(top_k, user_id=user_id)

        query_tokens = tokenize_for_search(query_text)
        query_compact = self._compact_text(query_text)

        scored: list[tuple[float, WorkingMemoryTurn]] = []
        with self._lock:
            scoped_turns = [t for t in self._buffer if self._matches_user(t.metadata, user_id)]
            total = max(1, len(scoped_turns))
            for idx, turn in enumerate(scoped_turns):
                user_text = turn.user_text or ""
                ai_text = turn.ai_text or ""
                combined = f"{user_text} {ai_text}".lower()
                combined_compact = self._compact_text(combined)

                lexical_matches = sum(1 for token in query_tokens if token and token in combined)
                lexical_score = lexical_matches / max(1, len(query_tokens))

                if query_compact and query_compact in combined_compact:
                    lexical_score = max(lexical_score, 0.85)

                if lexical_score <= 0:
                    continue

                recency_bonus = ((idx + 1) / total) * 0.1
                scored.append((lexical_score + recency_bonus, turn))

        scored.sort(reverse=True, key=lambda item: item[0])
        ordered_results: list[WorkingMemoryTurn] = [turn for _, turn in scored[:top_k]]

        # No lexical hit fallback is optional. Retrieval pipeline can disable it to avoid
        # injecting unrelated recent turns into the prompt.
        if allow_recent_fallback and len(ordered_results) < top_k:
            seen = {id(turn) for turn in ordered_results}
            for turn in self.get_recent(top_k, user_id=user_id):
                if id(turn) in seen:
                    continue
                ordered_results.append(turn)
                seen.add(id(turn))
                if len(ordered_results) >= top_k:
                    break

        return ordered_results[:top_k]
