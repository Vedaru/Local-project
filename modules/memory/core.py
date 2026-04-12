"""Human Memory Engine — MemPalace-backed orchestrator.

This module replaces Engram long-term storage with a Palace model:
  - Working memory: recent turns in RAM
  - Palace drawers: wing/room-organized verbatim long-term memory
  - Temporal knowledge graph: structured facts with validity windows
  - Episodic memory: conversation episodes (keeps C++ acceleration path)

Public API remains compatible with existing memory service usage.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..logging_config import get_logger
from ..memory_cpp_accel import load_memory_cpp_backend
from .episodic import EpisodicMemory
from .palace_kg import KgHit, PalaceKnowledgeGraph
from .palace_store import PalaceMemoryStore, detect_room, wing_for_user
from .working import WorkingMemory

logger = get_logger("Memory.Core")


def _get_core_project_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


@dataclass
class _MemoryHit:
    source: str
    content: str
    score: float
    created_at: float
    metadata: dict[str, Any]


@dataclass
class _CompatFact:
    fact_id: str
    content: str
    category: str
    confidence: float
    updated_at: float
    access_count: int = 0


class _EngramCompat:
    """Compatibility adapter for legacy fields used by tests and stats."""

    def __init__(self, palace_store: PalaceMemoryStore, default_wing: str):
        self._palace_store = palace_store
        self._default_wing = default_wing

    @property
    def total_slots_used(self) -> int:
        return self._palace_store.count()

    def save(self) -> None:
        self._palace_store.save()

    def retrieve(self, query: str, top_k: int = 5, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        wing = wing_for_user(user_id, self._default_wing) if user_id else None
        hits = self._palace_store.search(query, n_results=top_k, wing=wing, user_id=user_id)
        return [
            {
                "content": hit.text,
                "relevance": hit.similarity,
                "confidence": hit.similarity,
                "timestamp": hit.created_at,
                "metadata": hit.metadata,
            }
            for hit in hits
        ]


class _SemanticCompat:
    """Compatibility adapter that maps semantic operations to knowledge graph triples."""

    def __init__(self, kg: PalaceKnowledgeGraph):
        self._kg = kg

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    def save(self) -> None:
        self._kg.save()

    def count(self) -> int:
        return self._kg.count_current()

    def upsert(
        self,
        content: str,
        category: str = "general",
        confidence: float = 0.75,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> _CompatFact:
        text = (content or "").strip()
        if not text:
            return _CompatFact("", "", category, 0.0, time.time(), 0)

        payload = dict(metadata or {})
        if source:
            payload.setdefault("source", source)

        uid = self._normalize_user_id(payload.get("user_id"))
        subject = payload.get("subject", f"user:{uid or 'local'}")
        fact_id = self._kg.add_triple(
            subject=subject,
            predicate=category or "general",
            obj=text,
            user_id=uid,
            confidence=max(0.0, min(1.0, float(confidence))),
            metadata=payload,
        )

        return _CompatFact(
            fact_id=fact_id,
            content=text,
            category=category or "general",
            confidence=max(0.0, min(1.0, float(confidence))),
            updated_at=time.time(),
            access_count=0,
        )

    def search(self, query: str, top_k: int = 5, user_id: Optional[str] = None) -> list[_CompatFact]:
        hits = self._kg.search(query, top_k=top_k, user_id=user_id)
        return [
            _CompatFact(
                fact_id=hit.triple_id,
                content=hit.object,
                category=hit.predicate,
                confidence=hit.confidence,
                updated_at=hit.valid_from,
                access_count=int(hit.metadata.get("access_count", 0)),
            )
            for hit in hits
        ]

    def deactivate_matching(self, keyword: str) -> int:
        return self._kg.invalidate_matching(keyword)

    def apply_decay(self, _timestamp: float) -> None:
        # MemPalace KG keeps explicit validity windows; no confidence decay pass is required.
        return

    def resolve_contradictions(self) -> int:
        # Not auto-wired in this project yet; keep method for API compatibility.
        return 0


class _RetrievalCompat:
    def __init__(self, owner: "HumanMemoryEngine"):
        self._owner = owner

    def clear_cache(self) -> None:
        self._owner.clear_cache()


class MemoryConfig:
    """Centralized configuration for the MemPalace-based memory system."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

        # Working memory
        self.working_capacity = max(3, int(os.environ.get("MEMORY_WORKING_CAPACITY", "7")))

        # Palace long-term memory
        self.default_wing = os.environ.get("MEMORY_PALACE_DEFAULT_WING", "wing_local_project")
        self.palace_collection_name = os.environ.get("MEMORY_PALACE_COLLECTION", "mempalace_drawers")
        self.palace_base_dir = os.path.join(base_dir, "palace")

        # Knowledge graph
        self.kg_path = os.path.join(base_dir, "knowledge_graph.sqlite3")

        # Episodic memory
        self.episodes_path = os.path.join(base_dir, "episodes.jsonl")
        self.max_episodes = int(os.environ.get("MEMORY_MAX_EPISODES", "10000"))
        self.episode_similarity_threshold = float(os.environ.get("MEMORY_EPISODE_SIM_THRESHOLD", "0.2"))

        # One-time bootstrap from legacy files to new palace storage
        self.bootstrap_enabled = (
            (os.environ.get("MEMORY_PALACE_BOOTSTRAP_ENABLED", "1") or "1").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.bootstrap_max_episodes = max(
            100,
            int(os.environ.get("MEMORY_PALACE_BOOTSTRAP_MAX_EPISODES", "5000") or "5000"),
        )

        # Retrieval cache
        self.retrieval_cache_ttl = float(os.environ.get("MEMORY_RETRIEVAL_CACHE_TTL_SEC", "8"))
        self.retrieval_cache_size = int(os.environ.get("MEMORY_RETRIEVAL_CACHE_SIZE", "128"))

        # Context gate
        self.context_gate_enabled = (
            (os.environ.get("MEMORY_CONTEXT_GATE_ENABLED", "1") or "1").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.context_min_top_score = float(os.environ.get("MEMORY_CONTEXT_MIN_TOP_SCORE", "0.28") or "0.28")
        self.context_low_info_min_top_score = float(
            os.environ.get("MEMORY_CONTEXT_LOW_INFO_MIN_TOP_SCORE", "0.72") or "0.72"
        )
        self.context_low_info_max_chars = max(1, int(os.environ.get("MEMORY_CONTEXT_LOW_INFO_MAX_CHARS", "6") or "6"))
        self.context_low_info_max_tokens = max(1, int(os.environ.get("MEMORY_CONTEXT_LOW_INFO_MAX_TOKENS", "3") or "3"))
        self.context_low_info_max_unique_ratio = float(
            os.environ.get("MEMORY_CONTEXT_LOW_INFO_MAX_UNIQUE_RATIO", "0.78") or "0.78"
        )
        self.context_low_info_min_margin = float(
            os.environ.get("MEMORY_CONTEXT_LOW_INFO_MIN_MARGIN", "0.04") or "0.04"
        )
        self.context_normal_top_keep_ratio = float(
            os.environ.get("MEMORY_CONTEXT_NORMAL_TOP_KEEP_RATIO", "0.58") or "0.58"
        )
        self.context_low_info_top_keep_ratio = float(
            os.environ.get("MEMORY_CONTEXT_LOW_INFO_TOP_KEEP_RATIO", "0.92") or "0.92"
        )
        self.context_low_info_max_results = max(
            1,
            int(os.environ.get("MEMORY_CONTEXT_LOW_INFO_MAX_RESULTS", "1") or "1"),
        )

        # Working continuity fallback
        self.wm_continuity_fallback_enabled = (
            (os.environ.get("MEMORY_RETRIEVAL_WM_CONTINUITY_FALLBACK_ENABLED", "1") or "1").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.wm_continuity_max_age_sec = max(
            1.0,
            float(os.environ.get("MEMORY_RETRIEVAL_WM_CONTINUITY_MAX_AGE_SEC", "180") or "180"),
        )
        self.wm_continuity_max_results = max(
            1,
            int(os.environ.get("MEMORY_RETRIEVAL_WM_CONTINUITY_MAX_RESULTS", "2") or "2"),
        )
        self.wm_continuity_exclude_warmup = (
            (os.environ.get("MEMORY_RETRIEVAL_WM_CONTINUITY_EXCLUDE_WARMUP", "1") or "1").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        # Deferred persistence / warmup
        try:
            self.deferred_persist_interval_sec = max(
                0.5,
                float((os.environ.get("MEMORY_DEFERRED_PERSIST_INTERVAL_SEC", "6") or "6").strip()),
            )
        except Exception:
            self.deferred_persist_interval_sec = 6.0

        try:
            self.deferred_persist_turns = max(
                1,
                int((os.environ.get("MEMORY_DEFERRED_PERSIST_TURNS", "8") or "8").strip()),
            )
        except Exception:
            self.deferred_persist_turns = 8

        try:
            self.working_warmup_turns = max(
                0,
                int((os.environ.get("MEMORY_WORKING_WARMUP_TURNS", "4") or "4").strip()),
            )
        except Exception:
            self.working_warmup_turns = 4

        # C++ acceleration (episodic retrieval scoring)
        self.cpp_accel_lib = (os.environ.get("MEMORY_CPP_ACCEL_LIB", "") or "").strip()
        self.cpp_accel_required = (
            (os.environ.get("MEMORY_CPP_ACCEL_REQUIRED", "0") or "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        try:
            self.cpp_embedding_dim = max(64, int((os.environ.get("MEMORY_CPP_EMBED_DIM", "384") or "384").strip()))
        except Exception:
            self.cpp_embedding_dim = 384

        try:
            self.cpp_decay_rate = max(0.0, float((os.environ.get("MEMORY_CPP_DECAY_RATE", "0.0001") or "0.0001").strip()))
        except Exception:
            self.cpp_decay_rate = 0.0001

        try:
            self.cpp_worker_count = max(0, int((os.environ.get("MEMORY_CPP_WORKERS", "0") or "0").strip()))
        except Exception:
            self.cpp_worker_count = 0


class HumanMemoryEngine:
    """MemPalace-based memory manager with backward-compatible API."""

    def __init__(
        self,
        embedding_fn: Optional[Callable[[str], Any]] = None,
        llm_extract_fn: Optional[Callable[[str], dict[str, Any]]] = None,
        base_dir: Optional[str] = None,
    ):
        project_root = os.environ.get(
            "PROJECT_ROOT",
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )

        self._config = MemoryConfig(base_dir or os.path.join(project_root, "data", "memoripy"))
        self._embedding_fn = embedding_fn
        self._llm_extract_fn = llm_extract_fn
        self._lock = threading.RLock()
        self._init_time = time.time()

        self.memory_cpp_backend = load_memory_cpp_backend(
            explicit_library=self._config.cpp_accel_lib,
            required=self._config.cpp_accel_required,
        )

        self.working = WorkingMemory(capacity=self._config.working_capacity, embedding_fn=embedding_fn)
        self.episodic = EpisodicMemory(
            path=self._config.episodes_path,
            max_episodes=self._config.max_episodes,
            similarity_threshold=self._config.episode_similarity_threshold,
            cpp_backend=self.memory_cpp_backend,
            cpp_embedding_dim=self._config.cpp_embedding_dim,
            cpp_decay_rate=self._config.cpp_decay_rate,
            cpp_worker_count=self._config.cpp_worker_count,
        )
        self.palace = PalaceMemoryStore(
            base_dir=self._config.palace_base_dir,
            collection_name=self._config.palace_collection_name,
        )
        self.kg = PalaceKnowledgeGraph(db_path=self._config.kg_path)

        # Legacy compatibility aliases (still backed by new MemPalace subsystems).
        self.engram = _EngramCompat(self.palace, self._config.default_wing)
        self.semantic = _SemanticCompat(self.kg)
        self.retrieval = _RetrievalCompat(self)

        self.agent_bridge: Any = None
        try:
            from .agent_bridge import AgentMemoryBridge

            self.agent_bridge = AgentMemoryBridge(
                agent_memory_root=None,
                project_root=_get_core_project_root(),
            )
            if self.agent_bridge.enabled:
                stats = self.agent_bridge.get_stats()
                logger.info("[Agent桥接] 已连接 | 笔记数=%s", stats.get("total_notes", 0))
        except Exception as e:
            logger.debug("[Agent桥接] 初始化跳过: %s", e)

        self.enabled = True
        self.current_emotion = "neutral"
        self._turns_since_persist = 0
        self._last_persist_at = time.time()
        self._query_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

        self._bootstrap_palace_from_existing_memory()
        self._warm_working_memory_from_recent_episodes(max_turns=self._config.working_warmup_turns)

        logger.info("=" * 60)
        logger.info("HumanMemoryEngine (MemPalace) 已初始化")
        logger.info("  数据目录: %s", self._config.base_dir)
        logger.info("  C++加速: %s", bool(self.memory_cpp_backend))
        logger.info("  Drawer数: %s", self.palace.count())
        logger.info("  工作记忆容量: %s", self._config.working_capacity)
        logger.info("  KG事实: %s", self.kg.count_current())
        logger.info("  情景事件: %s", self.episodic.count())
        logger.info("=" * 60)

    # ===================================================================
    # Public API — these methods are used by memory_service/main.py
    # ===================================================================

    def store(self, content: str, metadata: Optional[dict] = None) -> str:
        """Store interaction content. Returns status string."""
        user_text, ai_text = self._parse_interaction(content)
        if not user_text or not ai_text:
            return "ignored-empty"

        md = dict(metadata or {})
        user_id = self._normalize_user_id(md.get("user_id"))
        disable_fact_extraction = bool(md.get("disable_fact_extraction", False))
        deferred_persist = bool(md.get("deferred_persist", False))

        self.record_interaction(
            user_text,
            ai_text,
            user_id=user_id,
            enable_fact_extraction=not disable_fact_extraction,
            immediate_persist=not deferred_persist,
            metadata=md,
        )
        return "stored"

    def retrieve(self, query: str, n_results: int = 5, user_id: Optional[str] = None) -> str:
        """Retrieve relevant memories as formatted context string."""
        scoped_user_id = self._normalize_user_id(user_id)
        if not query or not self.enabled:
            return self.working.get_context_string(user_id=scoped_user_id)

        cache_key = self._cache_key(query, scoped_user_id)
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        all_hits = self._collect_hits(query=query, n_results=n_results, user_id=scoped_user_id)
        gated_hits = self._apply_context_gate(query=query, hits=all_hits, n_results=n_results)
        context = self._format_hits(gated_hits, n_results=n_results)

        self._set_cache(cache_key, context)
        return context

    def record_interaction(
        self,
        user_text: str,
        ai_text: str,
        user_id: str = "",
        enable_fact_extraction: bool = True,
        immediate_persist: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Record one conversation turn through MemPalace pipeline."""
        user_text = (user_text or "").strip()
        ai_text = (ai_text or "").strip()
        if not user_text or not ai_text:
            return

        scoped_user_id = self._normalize_user_id(user_id)
        with self._lock:
            self.working.add_turn(
                user_text=user_text,
                ai_text=ai_text,
                metadata={"user_id": scoped_user_id, "source": "live_turn"} if scoped_user_id else {"source": "live_turn"},
            )

            wing = wing_for_user(scoped_user_id, default_wing=self._config.default_wing)
            room = detect_room(f"{user_text}\n{ai_text}")
            drawer_id = self.palace.add_drawer(
                wing=wing,
                room=room,
                content=f"用户: {user_text}\nAI: {ai_text}",
                user_id=scoped_user_id,
                metadata={
                    "type": "interaction",
                    "user_id": scoped_user_id,
                    "wing": wing,
                    "room": room,
                    "source": "conversation",
                },
            )

            self.episodic.add_episode(
                user_input=user_text,
                assistant_output=ai_text,
                metadata={
                    "type": "conversation",
                    "facts_extracted": 0,
                    "user_id": scoped_user_id,
                    "wing": wing,
                    "room": room,
                    "drawer_id": drawer_id,
                },
            )

            extracted_facts = self._extract_facts(user_text, scoped_user_id, enable_fact_extraction)
            if extracted_facts:
                self.episodic.add_episode(
                    user_input=user_text,
                    assistant_output=ai_text,
                    metadata={
                        "type": "fact_extraction",
                        "facts_extracted": len(extracted_facts),
                        "user_id": scoped_user_id,
                        "wing": wing,
                        "room": room,
                        "drawer_id": drawer_id,
                    },
                )

            self._persist_if_needed(force=immediate_persist)

        logger.debug("[交互记录] user='%s...' | facts=%s", user_text[:40], len(extracted_facts))

    def _extract_facts(self, user_text: str, user_id: str, enabled: bool) -> list[_CompatFact]:
        if not enabled or self._llm_extract_fn is None:
            return []

        extracted: list[_CompatFact] = []
        try:
            result = self._llm_extract_fn(
                f"从以下用户话语中提取关于用户的事实信息。返回JSON格式。\n用户话语: {user_text}"
            )
        except Exception as e:
            logger.debug("LLM事实提取失败(非致命): %s", e)
            return extracted

        if not isinstance(result, dict):
            return extracted

        facts_list = result.get("facts", [])
        if not isinstance(facts_list, list):
            return extracted

        for fact_data in facts_list:
            if not isinstance(fact_data, dict):
                continue
            fact_text = (fact_data.get("fact", "") or fact_data.get("content", "")).strip()
            if not fact_text:
                continue
            category = (fact_data.get("category", "general") or "general").strip().lower()
            confidence = fact_data.get("confidence", 0.75)
            try:
                confidence_f = min(max(float(confidence), 0.1), 1.0)
            except Exception:
                confidence_f = 0.75

            fact = self.semantic.upsert(
                content=fact_text,
                category=category,
                confidence=confidence_f,
                source="extracted_from_interaction",
                metadata={"user_id": user_id},
            )
            extracted.append(fact)

        return extracted

    def _bootstrap_palace_from_existing_memory(self) -> None:
        if not getattr(self._config, "bootstrap_enabled", True):
            return

        sentinel_path = os.path.join(self._config.base_dir, ".mempalace_bootstrap_done")
        if os.path.isfile(sentinel_path):
            return

        imported_drawers = 0
        imported_facts = 0

        # 1) Bootstrap drawers from legacy episodic records.
        try:
            episodes = list(getattr(self.episodic, "_episodes", []))
            if episodes:
                episodes = [ep for ep in episodes if getattr(ep, "active", True)]
                episodes.sort(key=lambda ep: float(getattr(ep, "timestamp", 0.0) or 0.0))
                episodes = episodes[-int(self._config.bootstrap_max_episodes) :]

                for ep in episodes:
                    user_text = (getattr(ep, "user_input", "") or "").strip()
                    ai_text = (getattr(ep, "assistant_output", "") or "").strip()
                    if not user_text or not ai_text:
                        continue

                    ep_metadata = getattr(ep, "metadata", {}) or {}
                    uid = self._normalize_user_id(ep_metadata.get("user_id"))
                    wing = wing_for_user(uid, default_wing=self._config.default_wing)
                    room = detect_room(f"{user_text}\n{ai_text}")

                    drawer_id = self.palace.add_drawer(
                        wing=wing,
                        room=room,
                        content=f"用户: {user_text}\nAI: {ai_text}",
                        user_id=uid,
                        metadata={
                            "type": "bootstrap_episode",
                            "user_id": uid,
                            "source": "legacy_episodes",
                            "episode_id": getattr(ep, "episode_id", ""),
                        },
                    )
                    if drawer_id:
                        imported_drawers += 1
        except Exception as exc:
            logger.debug("[启动迁移] 旧 episodes 导入跳过: %s", exc)

        # 2) Bootstrap KG facts from legacy semantic_facts.json.
        facts_path = os.path.join(self._config.base_dir, "semantic_facts.json")
        if os.path.isfile(facts_path):
            try:
                import json

                with open(facts_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                for raw in data.get("facts", []) if isinstance(data, dict) else []:
                    if not isinstance(raw, dict):
                        continue
                    if raw.get("active") is False:
                        continue

                    content = (raw.get("content") or "").strip()
                    if not content:
                        continue

                    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
                    category = (raw.get("category") or "general").strip().lower()
                    confidence = raw.get("confidence", 0.75)
                    try:
                        confidence_f = min(max(float(confidence), 0.1), 1.0)
                    except Exception:
                        confidence_f = 0.75

                    fact = self.semantic.upsert(
                        content=content,
                        category=category,
                        confidence=confidence_f,
                        source="legacy_semantic",
                        metadata=metadata,
                    )
                    if getattr(fact, "fact_id", ""):
                        imported_facts += 1
            except Exception as exc:
                logger.debug("[启动迁移] semantic_facts 导入跳过: %s", exc)

        try:
            with open(sentinel_path, "w", encoding="utf-8") as fh:
                fh.write(f"bootstrapped_at={time.time()}\n")
                fh.write(f"imported_drawers={imported_drawers}\n")
                fh.write(f"imported_facts={imported_facts}\n")
        except Exception:
            pass

        if imported_drawers > 0 or imported_facts > 0:
            logger.info(
                "[启动迁移] 已导入旧记忆 | drawers=%s | facts=%s",
                imported_drawers,
                imported_facts,
            )

    def _collect_hits(self, query: str, n_results: int, user_id: Optional[str]) -> list[_MemoryHit]:
        seen: set[tuple[str, str]] = set()
        merged: list[_MemoryHit] = []

        def _add(hit: _MemoryHit) -> None:
            key = (hit.source, hit.content)
            if key in seen:
                return
            seen.add(key)
            merged.append(hit)

        for hit in self._strategy_working(query, n_results=n_results, user_id=user_id):
            _add(hit)
        for hit in self._strategy_palace(query, n_results=n_results, user_id=user_id):
            _add(hit)
        for hit in self._strategy_kg(query, n_results=n_results, user_id=user_id):
            _add(hit)
        for hit in self._strategy_episodic(query, n_results=n_results, user_id=user_id):
            _add(hit)
        for hit in self._strategy_agent_memory(query, n_results=n_results):
            _add(hit)

        merged.sort(key=lambda item: (item.score, item.created_at), reverse=True)
        return merged

    def _strategy_working(self, query: str, n_results: int, user_id: Optional[str]) -> list[_MemoryHit]:
        hits: list[_MemoryHit] = []
        top_k = max(1, int(n_results or 1))
        now = time.time()

        turns = self.working.search(
            query,
            n_results=top_k,
            user_id=user_id,
            allow_recent_fallback=False,
        )

        continuity_turn_ids: set[int] = set()
        query_low_info = self._is_low_information_query(query)

        if turns and self._config.wm_continuity_exclude_warmup:
            filtered_turns = []
            for turn in turns:
                source = str((turn.metadata or {}).get("source", "")).strip().lower()
                if source != "episodic_warmup":
                    filtered_turns.append(turn)
                    continue

                turn_ts = float(turn.timestamp or 0.0)
                if turn_ts <= 0:
                    continue
                if max(0.0, now - turn_ts) <= self._config.wm_continuity_max_age_sec:
                    filtered_turns.append(turn)
            turns = filtered_turns

        if not turns and self._config.wm_continuity_fallback_enabled and not query_low_info:
            continuity_limit = min(top_k, max(1, self._config.wm_continuity_max_results))
            recent_pool = self.working.get_recent(n=max(top_k, continuity_limit), user_id=user_id)
            continuity_candidates = []
            for turn in reversed(recent_pool):
                metadata = turn.metadata or {}
                if self._config.wm_continuity_exclude_warmup:
                    source = str(metadata.get("source", "")).strip().lower()
                    if source == "episodic_warmup":
                        continue

                turn_ts = float(turn.timestamp or 0.0)
                if turn_ts <= 0:
                    continue
                age_sec = max(0.0, now - turn_ts)
                if age_sec > self._config.wm_continuity_max_age_sec:
                    continue

                continuity_candidates.append(turn)
                if len(continuity_candidates) >= continuity_limit:
                    break

            if continuity_candidates:
                turns = list(reversed(continuity_candidates))
                continuity_turn_ids = {id(turn) for turn in turns}

        for turn in turns:
            is_continuity_turn = id(turn) in continuity_turn_ids
            score = 0.62 if is_continuity_turn else 0.86
            source_name = "working_memory_continuity" if is_continuity_turn else "working_memory"
            hits.append(
                _MemoryHit(
                    source=source_name,
                    content=f"用户: {turn.user_text}\nAI: {turn.ai_text}",
                    score=score,
                    created_at=float(turn.timestamp or now),
                    metadata={"source": source_name},
                )
            )

        return hits

    def _strategy_palace(self, query: str, n_results: int, user_id: Optional[str]) -> list[_MemoryHit]:
        wing = wing_for_user(user_id, default_wing=self._config.default_wing) if user_id else None
        drawers = self.palace.search(
            query,
            n_results=max(3, n_results * 2),
            wing=wing,
            user_id=user_id,
        )

        hits: list[_MemoryHit] = []
        for hit in drawers:
            hits.append(
                _MemoryHit(
                    source="palace_drawer",
                    content=hit.text,
                    score=max(0.0, min(1.0, float(hit.similarity))),
                    created_at=hit.created_at,
                    metadata={
                        "source": "palace_drawer",
                        "wing": hit.wing,
                        "room": hit.room,
                        **(hit.metadata or {}),
                    },
                )
            )

        return hits

    def _strategy_kg(self, query: str, n_results: int, user_id: Optional[str]) -> list[_MemoryHit]:
        facts: list[KgHit] = self.kg.search(query, top_k=max(2, n_results), user_id=user_id)
        hits: list[_MemoryHit] = []
        for fact in facts:
            hits.append(
                _MemoryHit(
                    source="knowledge_graph",
                    content=f"{fact.subject} -> {fact.predicate}: {fact.object}",
                    score=max(0.0, min(1.0, float(fact.score))),
                    created_at=fact.valid_from,
                    metadata={
                        "source": "knowledge_graph",
                        "triple_id": fact.triple_id,
                        "predicate": fact.predicate,
                        **(fact.metadata or {}),
                    },
                )
            )
        return hits

    def _strategy_episodic(self, query: str, n_results: int, user_id: Optional[str]) -> list[_MemoryHit]:
        episodes = self.episodic.search(query, top_k=max(2, n_results), user_id=user_id)
        hits: list[_MemoryHit] = []
        for episode in episodes:
            hits.append(
                _MemoryHit(
                    source="episodic_event",
                    content=f"用户: {episode.user_input}\nAI: {episode.assistant_output}",
                    score=0.45,
                    created_at=float(episode.timestamp or time.time()),
                    metadata={
                        "source": "episodic_event",
                        "access_count": episode.access_count,
                        "type": (episode.metadata or {}).get("type", "conversation"),
                    },
                )
            )
        return hits

    def _strategy_agent_memory(self, query: str, n_results: int) -> list[_MemoryHit]:
        if self.agent_bridge is None or not getattr(self.agent_bridge, "enabled", False):
            return []

        try:
            bridge_hits = self.agent_bridge.search(query=query, top_k=max(2, n_results))
        except Exception:
            logger.debug("[检索][Agent桥接] 搜索失败")
            return []

        now = time.time()
        hits: list[_MemoryHit] = []
        for bridge_hit in bridge_hits:
            score = bridge_hit.relevance * 0.40 + (0.25 if bridge_hit.is_user_preference else 0.10) + 0.10
            hits.append(
                _MemoryHit(
                    source="agent_memory_bridge",
                    content=bridge_hit.content,
                    score=max(0.0, min(1.0, score)),
                    created_at=now - bridge_hit.age_hours * 3600,
                    metadata={
                        "source": "agent_memory_bridge",
                        "agent_scope": bridge_hit.scope,
                        "agent_file": bridge_hit.source_file,
                    },
                )
            )
        return hits

    def _is_low_information_query(self, query: str) -> bool:
        normalized = (query or "").strip()
        if not normalized:
            return True

        compact = "".join(normalized.split())
        if not compact:
            return True

        query_tokens = self._tokenize_for_gate(normalized)
        unique_ratio = len(set(compact)) / max(1, len(compact))
        is_brief = (
            len(compact) <= self._config.context_low_info_max_chars
            and len(query_tokens) <= self._config.context_low_info_max_tokens
        )
        is_low_diversity = (
            len(compact) <= self._config.context_low_info_max_chars
            and unique_ratio <= self._config.context_low_info_max_unique_ratio
        )
        return is_brief or is_low_diversity

    @staticmethod
    def _tokenize_for_gate(text: str) -> set[str]:
        from .text_search import tokenize_for_search

        return tokenize_for_search(text)

    def _apply_context_gate(self, query: str, hits: list[_MemoryHit], n_results: int) -> list[_MemoryHit]:
        if not self._config.context_gate_enabled or not hits:
            return hits[: max(1, n_results)]

        ranked = sorted(hits, key=lambda item: item.score, reverse=True)
        top_score = max(0.0, float(ranked[0].score))
        second_score = max(0.0, float(ranked[1].score)) if len(ranked) > 1 else 0.0
        score_margin = top_score - second_score

        low_info = self._is_low_information_query(query)
        required_top = self._config.context_low_info_min_top_score if low_info else self._config.context_min_top_score

        if top_score < required_top:
            return []

        if low_info and len(ranked) > 1 and score_margin < self._config.context_low_info_min_margin:
            return []

        keep_ratio = (
            self._config.context_low_info_top_keep_ratio
            if low_info
            else self._config.context_normal_top_keep_ratio
        )
        keep_ratio = min(max(0.0, float(keep_ratio)), 1.0)
        cutoff = max(required_top, top_score * keep_ratio)

        filtered = [item for item in ranked if float(item.score) >= cutoff]
        if not filtered:
            return []

        max_count = max(1, int(n_results or 1))
        if low_info:
            max_count = min(max_count, self._config.context_low_info_max_results)
        return filtered[:max_count]

    def _format_hits(self, hits: list[_MemoryHit], n_results: int) -> str:
        if not hits:
            return ""

        parts: list[str] = []

        wm_hits = [
            hit for hit in hits if hit.source in {"working_memory", "working_memory_continuity"}
        ][: max(1, n_results)]
        if wm_hits:
            lines = ["【最近对话】"]
            for hit in wm_hits:
                lines.append(hit.content)
            parts.append("\n".join(lines))

        palace_hits = [hit for hit in hits if hit.source == "palace_drawer"][: max(1, n_results)]
        if palace_hits:
            lines = ["【Palace记忆】"]
            for hit in palace_hits:
                wing = str(hit.metadata.get("wing", "wing_general"))
                room = str(hit.metadata.get("room", "general"))
                lines.append(f"[{wing}/{room}] {hit.content}")
            parts.append("\n".join(lines))

        kg_hits = [hit for hit in hits if hit.source == "knowledge_graph"][: max(1, n_results)]
        if kg_hits:
            lines = ["【知识图谱事实】"]
            for hit in kg_hits:
                lines.append(hit.content)
            parts.append("\n".join(lines))

        episodic_hits = [hit for hit in hits if hit.source == "episodic_event"][: max(1, n_results)]
        if episodic_hits:
            lines = ["【历史对话(用户输入)】"]
            for hit in episodic_hits:
                for line in hit.content.split("\n"):
                    line = line.strip()
                    if line.startswith("用户:") or line.lower().startswith("user:"):
                        lines.append(line)
            if len(lines) > 1:
                parts.append("\n".join(lines))

        agent_hits = [hit for hit in hits if hit.source == "agent_memory_bridge"][: max(1, n_results)]
        if agent_hits:
            lines = ["【Agent记忆】"]
            for hit in agent_hits:
                scope_label = str(hit.metadata.get("agent_scope", "")).strip()
                file_label = str(hit.metadata.get("agent_file", "")).strip()
                prefix = f"[{scope_label}] " if scope_label else ""
                lines.append(f"{prefix}{file_label}: {hit.content[:200]}...")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def _persist_if_needed(self, force: bool = False) -> None:
        self._turns_since_persist += 1
        now = time.time()

        should_flush = bool(force)
        if not should_flush:
            if self._turns_since_persist >= self._config.deferred_persist_turns:
                should_flush = True
            elif (now - self._last_persist_at) >= self._config.deferred_persist_interval_sec:
                should_flush = True

        if not should_flush:
            return

        try:
            self.engram.save()
            self.semantic.save()
            self.episodic.save()
            self._turns_since_persist = 0
            self._last_persist_at = now
        except Exception as e:
            logger.warning("[持久化] 写入异常(非致命): %s", e)

    def _warm_working_memory_from_recent_episodes(self, max_turns: int = 4) -> None:
        if max_turns <= 0:
            return
        try:
            recent = self.episodic.get_recent(n=max_turns)
            if not recent:
                return

            for episode in recent:
                user_text = (episode.user_input or "").strip()
                ai_text = (episode.assistant_output or "").strip()
                if not user_text or not ai_text:
                    continue

                episode_user_id = self._normalize_user_id((episode.metadata or {}).get("user_id"))
                self.working.add_turn(
                    user_text=user_text,
                    ai_text=ai_text,
                    metadata={
                        "source": "episodic_warmup",
                        "user_id": episode_user_id,
                    }
                    if episode_user_id
                    else {"source": "episodic_warmup"},
                    timestamp=episode.timestamp,
                )
        except Exception as exc:
            logger.debug("[工作记忆预热] 跳过: %s", exc)

    @staticmethod
    def _parse_interaction(content: str) -> tuple[str, str]:
        text = (content or "").replace("\\n", "\n").strip()
        if not text:
            return "", ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        prompt = ""
        output = ""

        def _after_colon(raw: str) -> str:
            for sep in (":", "："):
                if sep in raw:
                    return raw.split(sep, 1)[-1].strip()
            return raw.strip()

        for raw_line in lines:
            line = re.sub(r"^用户\([^)]*\)\s*[:：]\s*", "", raw_line)
            line = re.sub(r"^user\([^)]*\)\s*[:：]\s*", "", line, flags=re.IGNORECASE)
            lower = line.lower()

            if not prompt and (line.startswith("用户") or lower.startswith("user")):
                prompt = _after_colon(line)
                continue

            if not output and (line.startswith("AI") or lower.startswith("assistant")):
                output = _after_colon(line)
                continue

        if not prompt and len(lines) == 1:
            prompt = lines[0]

        return prompt.strip(), output.strip()

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    def _cache_key(self, query: str, user_id: Optional[str]) -> str:
        key = (query or "").strip().lower()
        uid = self._normalize_user_id(user_id)
        if not key:
            return ""
        return f"{uid}|{key}" if uid else f"*|{key}"

    def _get_cache(self, cache_key: str) -> Optional[str]:
        if not cache_key:
            return None
        with self._lock:
            item = self._query_cache.get(cache_key)
            if item is None:
                return None
            expires_at, payload = item
            if expires_at <= time.time():
                del self._query_cache[cache_key]
                return None
            self._query_cache.move_to_end(cache_key)
            return payload

    def _set_cache(self, cache_key: str, payload: str) -> None:
        if not cache_key:
            return
        ttl = self._config.retrieval_cache_ttl
        if not payload:
            ttl = min(ttl, 0.6)
        with self._lock:
            self._query_cache[cache_key] = (time.time() + ttl, payload)
            while len(self._query_cache) > self._config.retrieval_cache_size:
                self._query_cache.popitem(last=False)

    def clear_cache(self) -> None:
        with self._lock:
            self._query_cache.clear()

    def stats(self) -> dict[str, Any]:
        """Return comprehensive statistics."""
        return {
            "engine_uptime_seconds": time.time() - self._init_time,
            "enabled": self.enabled,
            "memory_cpp_accel_enabled": bool(self.memory_cpp_backend),
            "memory_cpp_accel_library": getattr(self.memory_cpp_backend, "library_path", ""),
            "working_memory_count": self.working.size,
            "working_memory_capacity": self._config.working_capacity,
            "engram_total_slots_used": self.palace.count(),
            "semantic_facts_active": self.kg.count_current(),
            "episodic_events": self.episodic.count(),
            "palace_default_wing": self._config.default_wing,
            "current_emotion": self.current_emotion,
        }

    def close(self):
        """Persist everything to disk."""
        with self._lock:
            try:
                self._persist_if_needed(force=True)
                self.palace.close()
                self.kg.close()
                self.episodic.save()
                self.clear_cache()
                logger.info("[关闭] 所有记忆已持久化到磁盘")
            except Exception as e:
                logger.error("[关闭] 持久化失败: %s", e)

    # ---- Legacy compat aliases ----

    @property
    def short_term_memory(self):
        """Backward-compat: working memory turns."""
        return self.working.get_recent()

    def retrieve_memories(self, query: str, n_results: int = 5, user_id: Optional[str] = None) -> str:
        return self.retrieve(query, n_results=n_results, user_id=user_id)

    def store_memory(self, conversation: str):
        self.store(conversation)

    def get_memory_stats(self) -> dict:
        return self.stats()

    def force_update_memory(self, old_info: str, new_info: str) -> bool:
        """Force-store a corrected fact with high confidence."""
        _ = old_info
        if not (new_info or "").strip():
            return False
        try:
            with self._lock:
                self.semantic.upsert(
                    content=new_info.strip(),
                    category="manual_correction",
                    confidence=0.98,
                    source="force_update",
                )
            logger.info("[强制更新] 注入更正记忆: %s...", new_info[:50])
            return True
        except Exception as e:
            logger.error("[强制更新] 失败: %s", e)
            return False

    def clear_about(self, keyword: str) -> int:
        """Deactivate memories matching a keyword."""
        count = 0
        try:
            with self._lock:
                count += self.palace.delete_matching(keyword)
                count += self.kg.invalidate_matching(keyword)
            logger.info("[清除记忆] 关键词 '%s', 清除 %s 条", keyword, count)
        except Exception as e:
            logger.error("[清除记忆] 失败: %s", e)
        return count

    def cleanup_old_memories(self):
        """Run maintenance: flush pending writes."""
        with self._lock:
            self._persist_if_needed(force=True)

    def resolve_all_contradictions(self):
        """Compatibility placeholder for contradiction resolver."""
        with self._lock:
            resolved = self.semantic.resolve_contradictions()
            if resolved > 0:
                logger.info("[矛盾解决] 解决了 %s 组矛盾事实", resolved)

    def summarize_day(self):
        """Generate daily summary of memory state."""
        s = self.stats()
        logger.info(
            "[每日总结] 工作记忆=%s | 活跃事实=%s | 情景事件=%s",
            s["working_memory_count"],
            s["semantic_facts_active"],
            s["episodic_events"],
        )
