"""Episodic Memory — event/experience log with embedding-based similarity.

Stores raw interaction events (user input + AI output) as episodes.
Supports semantic search via text overlap and optional embedding vectors.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .core_enums import MemoryTier
from .text_search import tokenize_for_search
from ..logging_config import get_logger

logger = get_logger("Memory.Episodic")


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

    def __init__(
        self,
        path: str,
        max_episodes: int = 2000,
        similarity_threshold: float = 0.2,
        embedding_fn=None,
        dim=None,
        cpp_backend=None,
        cpp_embedding_dim: int = 384,
        cpp_decay_rate: float = 0.0001,
        cpp_worker_count: int = 0,
    ):
        self.path = path
        self.max_episodes = max_episodes
        self.similarity_threshold = similarity_threshold
        self._cpp_backend = cpp_backend
        self._cpp_embedding_dim = max(64, int(cpp_embedding_dim or 384))
        self._cpp_decay_rate = max(0.0, float(cpp_decay_rate or 0.0))
        self._cpp_worker_count = max(0, int(cpp_worker_count or 0))
        self._lexical_weight = float(os.environ.get("MEMORY_EPISODIC_LEXICAL_WEIGHT", "0.7") or "0.7")
        self._recency_weight = float(os.environ.get("MEMORY_EPISODIC_RECENCY_WEIGHT", "0.3") or "0.3")
        self._cpp_weight = float(os.environ.get("MEMORY_EPISODIC_CPP_WEIGHT", "0.8") or "0.8")
        self._cpp_lexical_weight = float(os.environ.get("MEMORY_EPISODIC_CPP_LEXICAL_WEIGHT", "0.2") or "0.2")
        self._cpp_min_semantic_score = float(os.environ.get("MEMORY_EPISODIC_CPP_MIN_SEMANTIC_SCORE", "0.45") or "0.45")
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

        if episode.embedding is None and self._cpp_backend is not None:
            episode_embedding = self._build_embedding_for_episode(episode)
            if episode_embedding is not None:
                episode.embedding = episode_embedding

        with self._lock:
            self._episodes.append(episode)
            # Trim old inactive episodes
            if len(self._episodes) > self.max_episodes * 2:
                self._prune()
            # Append to JSONL immediately for durability
            self._append_to_jsonl(episode)

        return episode

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    @classmethod
    def _matches_user(cls, episode: Episode, user_id: Optional[str]) -> bool:
        uid = cls._normalize_user_id(user_id)
        if not uid:
            return True
        episode_uid = cls._normalize_user_id((episode.metadata or {}).get("user_id"))
        return episode_uid == uid

    def search(self, query: str, top_k: int = 5, user_id: Optional[str] = None) -> list[Episode]:
        """Search by keyword containment and recency."""
        query_words = tokenize_for_search(query)
        if not query_words:
            return []

        if self._cpp_backend is not None:
            try:
                accelerated = self._search_with_cpp(query, query_words=query_words, top_k=top_k, user_id=user_id)
                if accelerated:
                    return accelerated
            except Exception as exc:
                logger.debug("[情景记忆] cpp search fallback: %s", exc)

        scored: list[tuple[float, Episode]] = []
        now = time.time()

        with self._lock:
            for e in self._episodes:
                if not e.active:
                    continue
                if not self._matches_user(e, user_id):
                    continue

                combined_text = f"{e.user_input} {e.assistant_output}".lower()
                matches = sum(1 for w in query_words if w in combined_text)
                containment = matches / max(len(query_words), 1)

                # Avoid retrieving by recency only; require at least one lexical overlap
                # in the non-embedding search path.
                if containment <= 0.0:
                    continue

                # Recency bonus (newer is slightly more relevant)
                age_hours = (now - e.timestamp) / 3600.0
                recency_bonus = 1.0 / (1.0 + age_hours ** 0.5)

                score = containment * self._lexical_weight + recency_bonus * self._recency_weight

                # No keyword-based penalty — all episodes treated equally

                if score >= self.similarity_threshold:
                    scored.append((score, e))
                    e.access_count += 1

        scored.sort(reverse=True, key=lambda x: x[0])
        return [e for _, e in scored[:top_k]]

    def _build_embedding_for_episode(self, episode: Episode) -> Optional[list[float]]:
        if self._cpp_backend is None:
            return None

        text = f"{episode.user_input} {episode.assistant_output}".strip()
        if not text:
            return None

        embedding = self._cpp_backend.hash_embed_text(
            text,
            dimension=self._cpp_embedding_dim,
        )
        if not embedding or len(embedding) != self._cpp_embedding_dim:
            return None
        return [float(v) for v in embedding]

    def _ensure_episode_embedding(self, episode: Episode) -> Optional[list[float]]:
        embedding = episode.embedding
        if isinstance(embedding, list) and len(embedding) == self._cpp_embedding_dim:
            return [float(v) for v in embedding]

        computed = self._build_embedding_for_episode(episode)
        if computed is None:
            return None

        episode.embedding = computed
        return computed

    def _search_with_cpp(
        self,
        query: str,
        *,
        query_words: set[str],
        top_k: int,
        user_id: Optional[str] = None,
    ) -> list[Episode]:
        if self._cpp_backend is None:
            return []

        query_embedding = self._cpp_backend.hash_embed_text(
            query,
            dimension=self._cpp_embedding_dim,
        )
        if not query_embedding:
            return []

        candidates: list[Episode] = []
        candidate_embeddings: list[list[float]] = []
        timestamps: list[float] = []
        access_counts: list[int] = []
        decay_factors: list[float] = []
        lexical_scores: list[float] = []

        now = time.time()

        with self._lock:
            for episode in self._episodes:
                if not episode.active:
                    continue
                if not self._matches_user(episode, user_id):
                    continue

                embedding = self._ensure_episode_embedding(episode)
                if embedding is None:
                    continue

                combined_text = f"{episode.user_input} {episode.assistant_output}".lower()
                matches = sum(1 for word in query_words if word in combined_text)
                containment = matches / max(len(query_words), 1)

                candidates.append(episode)
                candidate_embeddings.append(embedding)
                timestamps.append(float(episode.timestamp))
                access_counts.append(max(1, int(episode.access_count)))
                decay_factors.append(1.0)
                lexical_scores.append(float(containment))

        if not candidates:
            return []

        adjusted = self._cpp_backend.compute_adjusted_scores(
            query_embedding=query_embedding,
            candidate_embeddings=candidate_embeddings,
            timestamps=timestamps,
            access_counts=access_counts,
            decay_factors=decay_factors,
            current_time=now,
            decay_rate=self._cpp_decay_rate,
            worker_count=self._cpp_worker_count,
        )
        if adjusted is None:
            return []

        adjusted_scores, _decays = adjusted
        if len(adjusted_scores) != len(candidates):
            return []

        ranked: list[tuple[float, Episode]] = []
        with self._lock:
            for index, episode in enumerate(candidates):
                cpp_score = max(0.0, float(adjusted_scores[index])) / 100.0
                lexical = lexical_scores[index]

                # If lexical overlap is zero, require enough semantic confidence from
                # C++ embedding scoring to avoid unrelated recency carry-over.
                if lexical <= 0.0 and cpp_score < self._cpp_min_semantic_score:
                    continue

                score = (cpp_score * self._cpp_weight) + (lexical * self._cpp_lexical_weight)

                if score >= self.similarity_threshold:
                    episode.access_count += 1
                    ranked.append((score, episode))

        ranked.sort(reverse=True, key=lambda item: item[0])
        return [episode for _, episode in ranked[:top_k]]

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
                except Exception as exc:
                    logger.debug("[情景记忆] backup failed: %s", exc)
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
        except Exception as exc:
            logger.warning("[情景记忆] save failed: %s", exc)

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
                    except Exception as exc:
                        logger.debug("[情景记忆] invalid line %s: %s", line_no, exc)
        except Exception as exc:
            logger.warning("[情景记忆] load failed: %s", exc)

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
        except Exception as exc:
            logger.warning("[情景记忆] append failed: %s", exc)

    def _prune(self):
        cutoff = time.time() - 86400 * 30
        self._episodes = [
            e for e in self._episodes
            if e.active or e.timestamp >= cutoff
        ]
