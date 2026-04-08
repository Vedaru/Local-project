"""Multi-strategy Retrieval Engine — human-like recall mechanism.

Implements a layered retrieval pipeline:
  1. Working Memory → recent context match
  2. Semantic Memory → structured fact lookup (Jaccard + containment)
  3. Episodic Memory → similar past events
  4. Agent Memory Bridge → one-way read from agent .md files (if available)

Results are merged, deduplicated, sorted by composite_score.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .core_enums import MemoryTier
from .working import WorkingMemory
from .semantic import SemanticMemory
from .episodic import EpisodicMemory
from .text_search import tokenize_for_search
from ..logging_config import get_logger

logger = get_logger("Retrieval")


def _env_float(name: str, default: float, *, minimum: Optional[float] = None) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw) if str(raw).strip() else float(default)
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_int(name: str, default: int, *, minimum: Optional[int] = None) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw) if str(raw).strip() else int(default)
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

        self._wm_conf_weight = _env_float("MEMORY_RETRIEVAL_WM_CONF_WEIGHT", 0.7, minimum=0.0)
        self._wm_relevance_weight = _env_float("MEMORY_RETRIEVAL_WM_REL_WEIGHT", 0.3, minimum=0.0)

        self._engram_relevance_weight = _env_float("MEMORY_RETRIEVAL_ENGRAM_REL_WEIGHT", 0.7, minimum=0.0)
        self._engram_conf_weight = _env_float("MEMORY_RETRIEVAL_ENGRAM_CONF_WEIGHT", 0.3, minimum=0.0)
        self._engram_bias = _env_float("MEMORY_RETRIEVAL_ENGRAM_BIAS", 0.15, minimum=0.0)

        self._semantic_conf_weight = _env_float("MEMORY_RETRIEVAL_SEMANTIC_CONF_WEIGHT", 0.85, minimum=0.0)
        self._semantic_bias = _env_float("MEMORY_RETRIEVAL_SEMANTIC_BIAS", 0.15, minimum=0.0)

        self._episodic_relevance_weight = _env_float("MEMORY_RETRIEVAL_EPISODIC_REL_WEIGHT", 0.5, minimum=0.0)
        self._episodic_accessed_bonus = _env_float("MEMORY_RETRIEVAL_EPISODIC_ACCESSED_BONUS", 0.15, minimum=0.0)
        self._episodic_unaccessed_bonus = _env_float("MEMORY_RETRIEVAL_EPISODIC_UNACCESSED_BONUS", 0.05, minimum=0.0)
        self._episodic_bias = _env_float("MEMORY_RETRIEVAL_EPISODIC_BIAS", 0.10, minimum=0.0)

        # Disable forced fallback-to-recent in retrieval pipeline by default.
        # This avoids unrelated memory carry-over for weak or generic inputs.
        self._wm_allow_recent_fallback = _env_bool(
            "MEMORY_RETRIEVAL_WM_ALLOW_RECENT_FALLBACK",
            False,
        )
        # Continuity fallback is narrower than generic recent fallback:
        # only for non-low-info queries, only very recent turns, and optionally
        # excluding episodic warmup turns to avoid reviving old topics.
        self._wm_continuity_fallback_enabled = _env_bool(
            "MEMORY_RETRIEVAL_WM_CONTINUITY_FALLBACK_ENABLED",
            True,
        )
        self._wm_continuity_max_age_sec = _env_float(
            "MEMORY_RETRIEVAL_WM_CONTINUITY_MAX_AGE_SEC",
            180.0,
            minimum=1.0,
        )
        self._wm_continuity_max_results = _env_int(
            "MEMORY_RETRIEVAL_WM_CONTINUITY_MAX_RESULTS",
            2,
            minimum=1,
        )
        self._wm_continuity_exclude_warmup = _env_bool(
            "MEMORY_RETRIEVAL_WM_CONTINUITY_EXCLUDE_WARMUP",
            True,
        )

        # Dynamic context gate (non-keyword): filter low-signal recalls by score,
        # query information density, and score spread.
        self._context_gate_enabled = _env_bool("MEMORY_CONTEXT_GATE_ENABLED", True)
        self._context_min_top_score = _env_float("MEMORY_CONTEXT_MIN_TOP_SCORE", 0.28, minimum=0.0)
        self._context_low_info_min_top_score = _env_float("MEMORY_CONTEXT_LOW_INFO_MIN_TOP_SCORE", 0.72, minimum=0.0)
        self._context_low_info_max_chars = _env_int("MEMORY_CONTEXT_LOW_INFO_MAX_CHARS", 6, minimum=1)
        self._context_low_info_max_tokens = _env_int("MEMORY_CONTEXT_LOW_INFO_MAX_TOKENS", 3, minimum=1)
        self._context_low_info_max_unique_ratio = _env_float("MEMORY_CONTEXT_LOW_INFO_MAX_UNIQUE_RATIO", 0.78, minimum=0.0)
        self._context_low_info_min_margin = _env_float("MEMORY_CONTEXT_LOW_INFO_MIN_MARGIN", 0.04, minimum=0.0)
        self._context_normal_top_keep_ratio = _env_float("MEMORY_CONTEXT_NORMAL_TOP_KEEP_RATIO", 0.58, minimum=0.0)
        self._context_low_info_top_keep_ratio = _env_float("MEMORY_CONTEXT_LOW_INFO_TOP_KEEP_RATIO", 0.92, minimum=0.0)
        self._context_low_info_max_results = _env_int("MEMORY_CONTEXT_LOW_INFO_MAX_RESULTS", 1, minimum=1)

        self._query_cache: OrderedDict[str, tuple[float, list[RetrievalResult]]] = OrderedDict()

    # ---- public API ----

    def multi_strategy_recall(self, query: str, n_results: int = 5, user_id: Optional[str] = None) -> str:
        """Execute full retrieval pipeline and return formatted string."""
        results = self.recall(query, n_results=n_results, user_id=user_id)
        gated = self._apply_context_gate(query=query, results=results, n_results=n_results)
        return self._format_results(gated, query, n_results)

    def recall(self, query: str, n_results: int = 5, user_id: Optional[str] = None) -> list[RetrievalResult]:
        """Execute all strategies and return merged ranked results."""
        cached = self._get_cache(query, user_id=user_id)
        if cached is not None:
            return cached

        seen_ids: set[str] = set()
        all_results: list[RetrievalResult] = []
        agent_hits: list[RetrievalResult] = []

        # Strategy 1: Working Memory
        wm_hits = self._strategy_working(query, n_results=max(2, n_results), user_id=user_id)
        for r in wm_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 2: Engram hash-addressed store
        engram_hits = self._strategy_engram(query, n_results=max(3, n_results), user_id=user_id)
        for r in engram_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 3: Semantic facts
        semantic_hits = self._strategy_semantic(query, n_results=max(3, n_results), user_id=user_id)
        for r in semantic_hits:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                all_results.append(r)

        # Strategy 4: Episodic events
        episodic_hits = self._strategy_episodic(query, n_results=max(3, n_results), user_id=user_id)
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

        all_results = [r for r in all_results if r.confidence >= self._min_confidence]

        all_results.sort(key=lambda r: r.composite_score, reverse=True)

        logger.debug(
            f"[检索] query='{query[:30]}' "
            f"| WM={len(wm_hits)}, Engram={len(engram_hits)}, Semantic={len(semantic_hits)}, Episodic={len(episodic_hits)}"
            f", Agent={len(agent_hits)}"
            f"| 合并去重后={len(all_results)}"
        )

        self._set_cache(query, all_results, user_id=user_id)
        return all_results[:n_results]

    def clear_cache(self):
        with self._lock:
            self._query_cache.clear()

    # ---- strategy implementations ----

    def _strategy_working(self, query: str, n_results: int, user_id: Optional[str] = None) -> list[RetrievalResult]:
        results = []
        top_k = max(1, int(n_results or 1))
        turns = self.working.search(
            query,
            n_results=top_k,
            user_id=user_id,
            allow_recent_fallback=self._wm_allow_recent_fallback,
        )

        continuity_turn_ids: set[int] = set()
        query_low_info = self._is_low_information_query(query)
        now = time.time()

        if turns and self._wm_continuity_exclude_warmup:
            filtered_turns = []
            for turn in turns:
                source = str((turn.metadata or {}).get("source", "")).strip().lower()
                if source != "episodic_warmup":
                    filtered_turns.append(turn)
                    continue

                turn_ts = float(turn.timestamp or 0.0)
                if turn_ts <= 0:
                    continue
                if max(0.0, now - turn_ts) <= self._wm_continuity_max_age_sec:
                    filtered_turns.append(turn)
            turns = filtered_turns

        if (
            not turns
            and self._wm_continuity_fallback_enabled
            and not query_low_info
        ):
            continuity_limit = min(top_k, max(1, self._wm_continuity_max_results))
            recent_pool = self.working.get_recent(
                n=max(top_k, continuity_limit),
                user_id=user_id,
            )
            continuity_candidates = []
            for turn in reversed(recent_pool):
                metadata = turn.metadata or {}
                if self._wm_continuity_exclude_warmup:
                    source = str(metadata.get("source", "")).strip().lower()
                    if source == "episodic_warmup":
                        continue

                turn_ts = float(turn.timestamp or 0.0)
                if turn_ts <= 0:
                    continue
                age_sec = max(0.0, now - turn_ts)
                if age_sec > self._wm_continuity_max_age_sec:
                    continue

                continuity_candidates.append(turn)
                if len(continuity_candidates) >= continuity_limit:
                    break

            if continuity_candidates:
                turns = list(reversed(continuity_candidates))
                continuity_turn_ids = {id(turn) for turn in turns}
                logger.debug(
                    "[检索-连续性补偿] query='%s' | 选取=%d | user_id=%s",
                    (query or "")[:30],
                    len(turns),
                    (user_id or "").strip() or "-",
                )

        for t in turns:
            is_continuity_turn = id(t) in continuity_turn_ids
            confidence = 0.62 if is_continuity_turn else 0.85
            relevance = 0.55 if is_continuity_turn else 0.8
            source_name = "working_memory_continuity" if is_continuity_turn else "working_memory"
            content = f"用户: {t.user_text}\nAI: {t.ai_text}"
            r = RetrievalResult(
                id=f"wm_{id(t)}",
                content=content,
                source_tier=MemoryTier.WORKING,
                confidence=confidence,
                relevance=relevance,
                composite_score=round(
                    confidence * self._wm_conf_weight + relevance * self._wm_relevance_weight,
                    4,
                ),
                created_at=t.timestamp or now,
                metadata={"source": source_name},
            )
            results.append(r)
        return results

    def _is_low_information_query(self, query: str) -> bool:
        normalized = (query or "").strip()
        if not normalized:
            return True

        compact = "".join(normalized.split())
        if not compact:
            return True

        query_tokens = tokenize_for_search(normalized)
        unique_ratio = len(set(compact)) / max(1, len(compact))
        is_brief = (
            len(compact) <= self._context_low_info_max_chars
            and len(query_tokens) <= self._context_low_info_max_tokens
        )
        is_low_diversity = (
            len(compact) <= self._context_low_info_max_chars
            and unique_ratio <= self._context_low_info_max_unique_ratio
        )
        return is_brief or is_low_diversity

    def _apply_context_gate(
        self,
        query: str,
        results: list[RetrievalResult],
        n_results: int,
    ) -> list[RetrievalResult]:
        if not self._context_gate_enabled or not results:
            return results

        ranked = sorted(results, key=lambda r: r.composite_score, reverse=True)
        top_score = max(0.0, float(ranked[0].composite_score))
        second_score = max(0.0, float(ranked[1].composite_score)) if len(ranked) > 1 else 0.0
        score_margin = top_score - second_score

        low_info = self._is_low_information_query(query)
        required_top = self._context_low_info_min_top_score if low_info else self._context_min_top_score

        if top_score < required_top:
            logger.debug(
                "[检索门控] 跳过记忆: top=%.3f < %.3f | low_info=%s | query='%s'",
                top_score,
                required_top,
                low_info,
                (query or "")[:40],
            )
            return []

        if low_info and len(ranked) > 1 and score_margin < self._context_low_info_min_margin:
            logger.debug(
                "[检索门控] 跳过记忆: low-info margin=%.3f < %.3f | query='%s'",
                score_margin,
                self._context_low_info_min_margin,
                (query or "")[:40],
            )
            return []

        normal_keep_ratio = min(max(self._context_normal_top_keep_ratio, 0.0), 1.0)
        low_info_keep_ratio = min(max(self._context_low_info_top_keep_ratio, 0.0), 1.0)
        keep_ratio = low_info_keep_ratio if low_info else normal_keep_ratio
        cutoff = max(required_top, top_score * keep_ratio)

        filtered = [item for item in ranked if float(item.composite_score) >= cutoff]
        if not filtered:
            return []

        max_count = max(1, int(n_results or 1))
        if low_info:
            max_count = min(max_count, self._context_low_info_max_results)
        return filtered[:max_count]

    def _strategy_engram(self, query: str, n_results: int, user_id: Optional[str] = None) -> list[RetrievalResult]:
        results = []
        if self.working and hasattr(self.working, '_engram_store_ref'):
            store = self.working._engram_store_ref  # type: ignore
            hits = store.retrieve(query, top_k=n_results, user_id=user_id)
            for h in hits:
                r = RetrievalResult(
                    id=f"engram_{hash(h.get('content', '')) % 100000}",
                    content=h.get("content", ""),
                    source_tier=MemoryTier.ENGRAM,
                    confidence=h.get("confidence", 0.5),
                    relevance=h.get("relevance", 0.5),
                    composite_score=round(
                        h.get("relevance", 0.6) * self._engram_relevance_weight
                        + h.get("confidence", 0.6) * self._engram_conf_weight
                        + self._engram_bias,
                        4,
                    ),
                    created_at=h.get("timestamp", time.time()),
                    metadata={"source": "engram_hash_lookup"},
                )
                results.append(r)
        return results

    def _strategy_semantic(self, query: str, n_results: int, user_id: Optional[str] = None) -> list[RetrievalResult]:
        results = []
        facts = self.semantic.search(query, top_k=n_results, user_id=user_id)
        now = time.time()
        for f in facts:
            r = RetrievalResult(
                id=f.fact_id,
                content=f.content,
                source_tier=MemoryTier.SEMANTIC,
                confidence=f.confidence,
                relevance=min(f.confidence, 1.0),
                composite_score=round(f.confidence * self._semantic_conf_weight + self._semantic_bias, 4),
                created_at=f.updated_at or now,
                metadata={
                    "source": "semantic_fact",
                    "category": f.category,
                    "access_count": f.access_count,
                },
            )
            results.append(r)
        return results

    def _strategy_episodic(self, query: str, n_results: int, user_id: Optional[str] = None) -> list[RetrievalResult]:
        results = []
        episodes = self.episodic.search(query, top_k=n_results, user_id=user_id)
        for e in episodes:
            content = f"用户: {e.user_input}\nAI: {e.assistant_output}"
            r = RetrievalResult(
                id=e.episode_id,
                content=content,
                source_tier=MemoryTier.EPISODIC,
                confidence=0.5,          # 低于Engram/Semantic，避免毒化
                relevance=0.4,           # 降低episodic相关性权重
                composite_score=round(
                    0.4 * self._episodic_relevance_weight
                    + (self._episodic_accessed_bonus if e.access_count > 0 else self._episodic_unaccessed_bonus)
                    + self._episodic_bias,
                    4,
                ),
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

        # 1. Working Memory — 最近对话上下文（最高优先级）
        wm_items = [r for r in results if r.source_tier == MemoryTier.WORKING][:n_results]
        if wm_items:
            lines = ["【最近对话】"]
            for r in wm_items:
                # WM already has "用户:...\nAI:..." format
                lines.append(r.content)
            parts.append("\n".join(lines))

        # 2. Engram / Semantic facts — 结构化知识（高可信度）
        # 过滤AI回复行，防止毒化LLM
        def _strip_ai_lines(text: str) -> str:
            """Remove AI reply lines from memory content."""
            return '\n'.join(
                line for line in text.split('\n')
                if not (line.startswith('AI:') or line.lower().startswith('assistant:'))
            )

        engram_items = [r for r in results if r.metadata.get("source") == "engram_hash_lookup"][:n_results]
        if engram_items:
            lines = ["【相关记忆】"]
            for r in engram_items:
                clean = _strip_ai_lines(r.content).strip()
                if clean:
                    lines.append(clean)
            parts.append("\n".join(lines))

        semantic_items = [
            r for r in results
            if r.source_tier == MemoryTier.SEMANTIC
            and r.metadata.get("source") != "engram_hash_lookup"
            and r.metadata.get("source") != "agent_memory_bridge"
        ][:n_results]
        if semantic_items:
            lines = ["【已知事实】"]
            for r in semantic_items:
                lines.append(r.content)
            parts.append("\n".join(lines))

        # 3. Episodic — 只输出用户输入（不含AI回复，避免毒化LLM）
        episodic_items = [r for r in results if r.source_tier == MemoryTier.EPISODIC][:n_results]
        if episodic_items:
            lines = ["【历史对话(用户输入)】"]
            for r in episodic_items:
                # 只提取用户输入行，不包含AI回复
                content_lines = r.content.split('\n')
                user_lines = [l for l in content_lines if l.startswith('用户:') or l.lower().startswith('user:')]
                if user_lines:
                    lines.extend(user_lines)
            if len(lines) > 1:
                parts.append("\n".join(lines))

        # 4. Agent Memory Bridge
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

    @staticmethod
    def _cache_key(query: str, user_id: Optional[str] = None) -> str:
        key = (query or "").strip().lower()
        if not key:
            return ""
        uid = (user_id or "").strip()
        return f"{uid}|{key}" if uid else f"*|{key}"

    def _get_cache(self, query: str, user_id: Optional[str] = None) -> Optional[list[RetrievalResult]]:
        key = self._cache_key(query, user_id=user_id)
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

    def _set_cache(self, query: str, results: list[RetrievalResult], user_id: Optional[str] = None):
        key = self._cache_key(query, user_id=user_id)
        if not key:
            return
        ttl = self._cache_ttl
        if not results:
            ttl = min(ttl, 0.6)
        with self._lock:
            self._query_cache[key] = (time.time() + ttl, list(results))
            while len(self._query_cache) > self._cache_size:
                self._query_cache.popitem(last=False)
