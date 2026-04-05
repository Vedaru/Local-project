"""Multi-strategy Retrieval Engine — human-like recall mechanism.

Implements a layered retrieval pipeline:
  1. Working Memory → recent context match
  2. Semantic Memory → structured fact lookup (Jaccard + containment)
  3. Episodic Memory → similar past events
  4. Agent Memory Bridge → one-way read from agent .md files (if available)

Results are merged, deduplicated, sorted by composite_score.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .core_enums import MemoryTier, MemoryItem
from .working import WorkingMemory
from .semantic import SemanticMemory, Fact
from .episodic import EpisodicMemory, Episode
from ..logging_config import get_logger

logger = get_logger("Retrieval")


@dataclass
class RetrievalResult:
    id: str = ""
    content: str = ""
    source_tier: MemoryTier = MemoryTier.WORKING
    confidence: float = 0.5
    relevance: float = 0.0
    composite_score: float = 0.0
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalEngine:
    """Multi-strategy retrieval engine with LRU cache."""

    def __init__(
        self,
        working_memory: WorkingMemory,
        semantic_memory: SemanticMemory,
        episodic_memory: EpisodicMemory,
        engram_store=None,
        engram_tokenizer=None,
        embedding_fn: Optional[Callable[[str], Any]] = None,
        cache_ttl: float = 8.0,
        cache_size: int = 128,
        min_confidence: float = 0.15,
        agent_bridge: Optional[Any] = None,
    ):
        self.working = working_memory
        self.semantic = semantic_memory
        self.episodic = episodic_memory
        self.agent_bridge = agent_bridge
        self._embedding_fn = embedding_fn
        self._cache_ttl = cache_ttl
        self._cache_size = max(16, cache_size)
        self._min_confidence = min_confidence
        self._lock = threading.RLock()

        self._query_cache: OrderedDict[str, tuple[float, list[RetrievalResult]]] = OrderedDict()

    # ---- public API ----

    def multi_strategy_recall(self, query: str, n_results: int = 5) -> str:
        """Execute full retrieval pipeline and return formatted string."""
        results = self.recall(query, n_results=n_results)
        return self._format_results(results, query, n_results)

    def recall(self, query: str, n_results: int = 5) -> list[RetrievalResult]:
        """Execute all strategies and return merged ranked results."""
        cached = self._get_cache(query)
        if cached is not None:
            return cached

        seen_ids: set[str] = set()
        all_results: list[RetrievalResult] = []

        now = time.time()

        # Strategy 1: Working Memory
        wm_hits = self._strategy_working(query, n_results=max(2, n_results))
        for r in wm_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 2: Engram hash-addressed store
        engram_hits = self._strategy_engram(query, n_results=max(3, n_results))
        for r in engram_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 3: Semantic facts
        semantic_hits = self._strategy_semantic(query, n_results=max(3, n_results))
        for r in semantic_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 4: Episodic events
        episodic_hits = self._strategy_episodic(query, n_results=max(3, n_results))
        for r in episodic_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 5: Agent Memory Bridge
        if self.agent_bridge is not None and getattr(self.agent_bridge, 'enabled', False):
            agent_hits = self._strategy_agent_memory(query, n_results=max(2, n_results))
            for r in agent_hits:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    all_results.append(r)

        all_results.sort(key=lambda r: r.composite_score, reverse=True)

        _agent_hit_count = len(agent_hits) if 'agent_hits' in dir() else 0
        logger.debug(
            f"[检索] query='{query[:30]}' "
            f"| WM={len(wm_hits)}, Engram={len(engram_hits)}, Semantic={len(semantic_hits)}, Episodic={len(episodic_hits)}"
            f", Agent={_agent_hit_count}"
            f"| 合并去重后={len(all_results)}"
        )

        self._set_cache(query, all_results)
        return all_results[:n_results]

    def clear_cache(self):
        with self._lock:
            self._query_cache.clear()

    # ---- strategy implementations ----

    def _strategy_working(self, query: str, n_results: int) -> list[RetrievalResult]:
        results = []
        turns = self.working.search(query, n_results=n_results)
        now = time.time()
        for t in turns:
            content = f"用户: {t.user_text}\nAI: {t.ai_text}"
            r = RetrievalResult(
                id=f"wm_{id(t)}",
                content=content,
                source_tier=MemoryTier.WORKING,
                confidence=0.85,
                relevance=0.8,
                composite_score=round(0.85 * 0.7 + 0.8 * 0.3, 4),
                created_at=t.timestamp or now,
                metadata={"source": "working_memory"},
            )
            results.append(r)
        return results

    def _strategy_engram(self, query: str, n_results: int) -> list[RetrievalResult]:
        results = []
        if self.working and hasattr(self.working, '_engram_store_ref'):
            store = self.working._engram_store_ref  # type: ignore
            hits = store.retrieve(query, top_k=n_results)
            for h in hits:
                r = RetrievalResult(
                    id=f"engram_{hash(h.get('content', '')) % 100000}",
                    content=h.get("content", ""),
                    source_tier=MemoryTier.ENGRAM,
                    confidence=h.get("confidence", 0.5),
                    relevance=h.get("relevance", 0.5),
                    composite_score=round(h.get("relevance", 0.5) * 0.6 + h.get("confidence", 0.5) * 0.4, 4),
                    created_at=h.get("timestamp", time.time()),
                    metadata={"source": "engram_hash_lookup"},
                )
                results.append(r)
        return results

    def _strategy_semantic(self, query: str, n_results: int) -> list[RetrievalResult]:
        results = []
        facts = self.semantic.search(query, top_k=n_results)
        now = time.time()
        for f in facts:
            r = RetrievalResult(
                id=f.fact_id,
                content=f.content,
                source_tier=MemoryTier.SEMANTIC,
                confidence=f.confidence,
                relevance=min(f.confidence, 1.0),
                composite_score=round(f.confidence * 0.9, 4),
                created_at=f.updated_at or now,
                metadata={
                    "source": "semantic_fact",
                    "category": f.category,
                    "access_count": f.access_count,
                },
            )
            results.append(r)
        return results

    def _strategy_episodic(self, query: str, n_results: int) -> list[RetrievalResult]:
        results = []
        episodes = self.episodic.search(query, top_k=n_results)
        for e in episodes:
            content = f"用户: {e.user_input}\nAI: {e.assistant_output}"
            r = RetrievalResult(
                id=e.episode_id,
                content=content,
                source_tier=MemoryTier.EPISODIC,
                confidence=0.6,
                relevance=0.55,
                composite_score=round(0.55 * 0.6 + (0.25 if e.access_count > 0 else 0.10) + 0.15, 4),
                created_at=e.timestamp,
                metadata={
                    "source": "episodic_event",
                    "type": e.metadata.get("type", "conversation"),
                    "access_count": e.access_count,
                },
            )
            results.append(r)
        return results

    def _strategy_agent_memory(self, query: str, n_results: int = 3) -> list[RetrievalResult]:
        results = []
        if self.agent_bridge is None:
            return results

        try:
            hits = self.agent_bridge.search(query=query, top_k=n_results)
        except Exception:
            logger.debug("[检索][Agent桥接] 搜索失败")
            return results

        if not hits:
            return results

        now = time.time()
        for hit in hits:
            display_content = hit.content
            if len(display_content) > 500:
                display_content = (
                    display_content[:200].rstrip()
                    + "\n\n... [截省] ...\n\n"
                    + display_content[-300:].lstrip()
                )

            r = RetrievalResult(
                id=f"agent_{hash(hit.source_file) % 100000}",
                content=display_content,
                source_tier=MemoryTier.SEMANTIC,
                confidence=min(0.80 + hit.relevance * 0.2, 1.0),
                relevance=hit.relevance,
                composite_score=round(
                    hit.relevance * 0.40
                    + (0.25 if hit.is_user_preference else 0.10)
                    + (1.0 / (1.0 + hit.age_hours ** 0.5)) * 0.15
                    + 0.10,
                    4,
                ),
                created_at=now - hit.age_hours * 3600,
                metadata={
                    "source": "agent_memory_bridge",
                    "agent_scope": hit.scope,
                    "agent_file": hit.source_file,
                },
            )
            results.append(r)

        results.sort(key=lambda r: r.composite_score, reverse=True)
        return results

    # ---- formatting ----

    def _format_results(self, results: list[RetrievalResult], query: str, n_results: int) -> str:
        parts: list[str] = []

        engram_items = [r for r in results if r.metadata.get("source") == "engram_hash_lookup"][:n_results]
        semantic_items = [
            r for r in results
            if r.source_tier == MemoryTier.SEMANTIC
            and r.metadata.get("source") != "engram_hash_lookup"
            and r.metadata.get("source") != "agent_memory_bridge"
        ][:n_results]
        episodic_items = [r for r in results if r.source_tier == MemoryTier.EPISODIC][:n_results]

        if engram_items:
            lines = ["【Engram记忆】"]
            for r in engram_items:
                lines.append(r.content)
            parts.append("\n".join(lines))

        if semantic_items:
            lines = ["【已知事实】"]
            for r in semantic_items:
                lines.append(r.content)
            parts.append("\n".join(lines))

        if episodic_items:
            lines = ["【相关回忆】"]
            for r in episodic_items:
                lines.append(r.content)
            parts.append("\n".join(lines))

        agent_items = [r for r in results if r.metadata.get("source") == "agent_memory_bridge"][:n_results]
        if agent_items:
            lines = ["【Agent记忆】"]
            for r in agent_items:
                scope_label = r.metadata.get("agent_scope", "")
                file_label = r.metadata.get("agent_file", "")
                label = f"[{scope_label}] " if scope_label else ""
                lines.append(f"{label}{file_label}: {r.content[:200]}...")
            parts.append("\n".join(lines))

        result = "\n\n".join(parts)

        if result:
            tier_counts = {
                MemoryTier.WORKING: sum(1 for r in results if r.source_tier == MemoryTier.WORKING),
                MemoryTier.SEMANTIC: sum(1 for r in results if r.source_tier == MemoryTier.SEMANTIC),
                MemoryTier.EPISODIC: sum(1 for r in results if r.source_tier == MemoryTier.EPISODIC),
            }
            agent_count = len(agent_items)
            logger.debug(
                f"[检索结果] 返回 {len(results)} 条 "
                f"(工作={tier_counts[MemoryTier.WORKING]}, 语义={tier_counts[MemoryTier.SEMANTIC]}, "
                f"情景={tier_counts[MemoryTier.EPISODIC]}, Agent={agent_count})"
            )

        return result

    # ---- cache helpers ----

    def _get_cache(self, query: str) -> Optional[list[RetrievalResult]]:
        key = (query or "").strip().lower()
        if not key:
            return None
        with self._lock:
            item = self._query_cache.get(key)
            if item is None:
                return None
            expires_at, payload = item
            if expires_at <= time.time():
                del self._query_cache[key]
                return None
            self._query_cache.move_to_end(key)
            return list(payload)

    def _set_cache(self, query: str, results: list[RetrievalResult]):
        key = (query or "").strip().lower()
        if not key:
            return
        ttl = self._cache_ttl
        if not results:
            ttl = min(ttl, 0.6)
        with self._lock:
            self._query_cache[key] = (time.time() + ttl, list(results))
            while len(self._query_cache) > self._cache_size:
                self._query_cache.popitem(last=False)
