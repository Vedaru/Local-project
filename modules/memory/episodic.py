"""Episodic Memory — event/experience log with embedding-based similarity.

Stores raw interaction events (user input + AI output) as episodes.
Supports semantic search via text overlap and optional embedding vectors.
"""

from __future__ import annotations

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from .core_enums import MemoryTier


@dataclass
class Episode:
    episode_id: str = ""
    user_input: str = ""
    assistant_output: str = ""
    timestamp: float = 0.0
    embedding: Optional[list] = None  # Optional numpy vector serialized to list
    metadata: dict[str, Any] = None
    active: bool = True
    access_count: int = 0

    def __post_init__(self):
        if not self.episode_id:
            self.episode_id = str(uuid.uuid4())[:12]
        if not self.timestamp:
            self.timestamp = time.time()
        if self.metadata is None:
            self.metadata = {}


class EpisodicMemory:
    """Thread-safe episodic memory store with JSONL persistence."""

    def __init__(self, path: str, max_episodes: int = 2000, similarity_threshold: float = 0.2, embedding_fn=None, dim=None):
        self.path = path
        self.max_episodes = max_episodes
        self.similarity_threshold = similarity_threshold
        self._episodes: list[Episode] = []
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        self._load()

    @property
    def _episodes_count(self) -> int:
        return sum(1 for e in self._episodes if e.active)

    def count(self) -> int:
        return self._episodes_count

    def add_episode(
        self,
        user_input: str,
        assistant_output: str,
        embedding: Optional[Any] = None,
        metadata: Optional[dict] = None,
    ) -> Episode:
        episode = Episode(
            user_input=user_input,
            assistant_output=assistant_output,
            embedding=list(embedding) if embedding is not None and hasattr(embedding, "__iter__") else None,
            metadata=metadata or {},
        )

        with self._lock:
            self._episodes.append(episode)
            # Trim old inactive episodes
            if len(self._episodes) > self.max_episodes * 2:
                self._prune()
            # Append to JSONL immediately for durability
            self._append_to_jsonl(episode)

        return episode

    def search(self, query: str, top_k: int = 5) -> list[Episode]:
        """Search by keyword containment and recency."""
        query_words = set((query or "").lower().split())
        if not query_words:
            return []

        scored: list[tuple[float, Episode]] = []
        now = time.time()

        with self._lock:
            for e in self._episodes:
                if not e.active:
                    continue

                combined_text = f"{e.user_input} {e.assistant_output}".lower()
                matches = sum(1 for w in query_words if len(w) > 1 and w in combined_text)
                containment = matches / max(len(query_words), 1)

                # Recency bonus (newer is slightly more relevant)
                age_hours = (now - e.timestamp) / 3600.0
                recency_bonus = 1.0 / (1.0 + age_hours ** 0.5)

                score = containment * 0.7 + recency_bonus * 0.3

                # No keyword-based penalty — all episodes treated equally

                if score >= self.similarity_threshold:
                    scored.append((score, e))
                    e.access_count += 1

        scored.sort(reverse=True, key=lambda x: x[0])
        return [e for _, e in scored[:top_k]]

    def get_recent(self, n: int = 10) -> list[Episode]:
        with self._lock:
            active = [e for e in self._episodes if e.active]
        return active[-n:] if n > 0 else []

    # ---- persistence ----

    def save(self):
        """Full save of all episodes."""
        target = self.path
        if not target:
            return
        backup = target + ".bak"
        tmp = target + ".tmp"

        try:
            if os.path.isfile(target):
                import shutil
                try:
                    shutil.copy2(target, backup)
                except Exception:
                    pass
            with open(tmp, "w", encoding="utf-8") as fh:
                for e in self._episodes:
                    row = {
                        "episode_id": e.episode_id,
                        "user_input": e.user_input,
                        "assistant_output": e.assistant_output,
                        "timestamp": e.timestamp,
                        "embedding": e.embedding,
                        "metadata": e.metadata,
                        "active": e.active,
                        "access_count": e.access_count,
                    }
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp, target)
        except Exception:
            pass

    # ---- internal ----

    def _load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        e = Episode(**{k: v for k, v in raw.items() if hasattr(Episode, k)})
                        self._episodes.append(e)
                    except Exception:
                        pass
        except Exception:
            pass

    def _append_to_jsonl(self, episode: Episode):
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                row = {
                    "episode_id": episode.episode_id,
                    "user_input": episode.user_input,
                    "assistant_output": episode.assistant_output,
                    "timestamp": episode.timestamp,
                    "embedding": episode.embedding,
                    "metadata": episode.metadata,
                    "active": True,
                    "access_count": 0,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _prune(self):
        cutoff = time.time() - 86400 * 30
        self._episodes = [
            e for e in self._episodes
            if e.active or e.timestamp >= cutoff
        ]
