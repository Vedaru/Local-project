"""
Human Memory Engine — Core orchestrator for an Engram-based memory system.

Architecture:
┌─────────────────────────────────────────────────────┐
│                  HumanMemoryEngine                   │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Working  │→ │  Engram     │←→│   Episodic     │  │
│  │ Memory   │  │  (N-gram    │  │  (Episodes)    │  │
│  │ ~7 items │  │   Hash)     │  │  Event log     │  │
│  └────┬─────┘  └─────────────┘  └────────────────┘  │
│       ↓               ↓                ↓           │
│  ┌──────────────────────────────────────────────┐   │
│  │          Retrieval Engine                     │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘

All long-term storage uses Engram N-gram hash-addressed tables.
Runtime path avoids direct FAISS / NetworkX usage (compat dependencies may still exist for legacy workflows).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

from ..logging_config import get_logger
from ..memory_cpp_accel import load_memory_cpp_backend
from .engram_config import EngramConfig
from .engram_store import EngramMemoryStore
from .working import WorkingMemory
from .semantic import SemanticMemory
from .episodic import EpisodicMemory
from .retrieval import RetrievalEngine


def _get_core_project_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

logger = get_logger("Memory.Core")


class MemoryConfig:
    """Centralized configuration for all memory subsystems."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

        # Working memory
        self.working_capacity = max(3, int(os.environ.get("MEMORY_WORKING_CAPACITY", "7")))

        # Engram config
        self.engram_base_dir = os.path.join(base_dir, "engram")

        # Semantic memory (facts)
        self.facts_path = os.path.join(base_dir, "semantic_facts.json")
        self.min_fact_confidence = float(os.environ.get("MEMORY_MIN_FACT_CONFIDENCE", "0.15"))
        self.fact_decay_rate = float(os.environ.get("MEMORY_FACT_DECAY_RATE", "1.02"))
        self.max_facts_per_slot = int(os.environ.get("MEMORY_MAX_FACTS_PER_SLOT", "20"))

        # Episodic memory (events)
        self.episodes_path = os.path.join(base_dir, "episodes.jsonl")
        self.max_episodes = int(os.environ.get("MEMORY_MAX_EPISODES", "10000"))
        self.episode_similarity_threshold = float(os.environ.get("MEMORY_EPISODE_SIM_THRESHOLD", "0.2"))

        # Retrieval
        self.retrieval_cache_ttl = float(os.environ.get("MEMORY_RETRIEVAL_CACHE_TTL_SEC", "8"))
        self.retrieval_cache_size = int(os.environ.get("MEMORY_RETRIEVAL_CACHE_SIZE", "128"))
        self.retrieval_min_confidence = float(os.environ.get("MEMORY_RETRIEVAL_MIN_CONFIDENCE", "0.15"))

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


# ---------------------------------------------------------------------------
# Public API class — this IS the MemoryManager used by memory_service
# ---------------------------------------------------------------------------

class HumanMemoryEngine:
    """
    Engram-based human-like memory system.

    Coordinates:
      - WorkingMemory: short-term buffer (~7 items)
      - EngramMemoryStore: O(1) hash-addressed long-term memory
      - SemanticMemory: structured fact storage (JSON-backed)
      - EpisodicMemory: event log (JSONL-backed)
      - RetrievalEngine: multi-strategy recall

    Thread-safe via internal lock.
    """

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

        # ---- Subsystem 1: Engram Store (core long-term storage) ----
        _ecfg = EngramConfig(persist_dir=self._config.engram_base_dir)
        _ecfg.base_dir = self._config.engram_base_dir
        # Ensure EngramConfig has all attrs expected by EngramMemoryStore / NgramHashMapper
        if not hasattr(_ecfg, 'ngram_n_values'):
            # ngram_n_values: e.g., (2,) for bigrams only when max_ngram_size=3 → range(2,3) = (2,)
            # but we want both bigram+trigram: (2, 3)
            _ecfg.ngram_n_values = tuple(range(2, max(3, _ecfg.max_ngram_size) + 1))
        if not hasattr(_ecfg, 'prime_moduli'):
            primes_list = list(_ecfg.engram_vocab_sizes) if len(_ecfg.engram_vocab_sizes) >= _ecfg.n_head_per_ngram else [
                500003, 499979, 499969, 499957,
            ]
            _ecfg.prime_moduli = tuple(primes_list[:_ecfg.n_head_per_ngram])
        self.engram = EngramMemoryStore(config=_ecfg)

        # ---- Subsystem 2: Working Memory ----
        self.working = WorkingMemory(
            capacity=self._config.working_capacity,
            embedding_fn=embedding_fn,
        )
        # Wire engram ref for retrieval engine access
        self.working._engram_store_ref = self.engram  # type: ignore[attr-defined]

        # ---- Subsystem 3: Semantic Facts ----
        self.semantic = SemanticMemory(
            path=self._config.facts_path,
            min_confidence=self._config.min_fact_confidence,
            decay_rate=self._config.fact_decay_rate,
            max_facts_per_slot=self._config.max_facts_per_slot,
        )

        # ---- Subsystem 4: Episodic Events ----
        self.episodic = EpisodicMemory(
            path=self._config.episodes_path,
            max_episodes=self._config.max_episodes,
            similarity_threshold=self._config.episode_similarity_threshold,
            cpp_backend=self.memory_cpp_backend,
            cpp_embedding_dim=self._config.cpp_embedding_dim,
            cpp_decay_rate=self._config.cpp_decay_rate,
            cpp_worker_count=self._config.cpp_worker_count,
        )

        # ---- Subsystem 5: Retrieval Engine ----
        self.retrieval = RetrievalEngine(
            working_memory=self.working,
            semantic_memory=self.semantic,
            episodic_memory=self.episodic,
            embedding_fn=embedding_fn,
            cache_ttl=self._config.retrieval_cache_ttl,
            cache_size=self._config.retrieval_cache_size,
            min_confidence=self._config.retrieval_min_confidence,
        )

        # ---- Agent Memory Bridge (optional, read-only) ----
        self.agent_bridge: Any = None
        try:
            from .agent_bridge import AgentMemoryBridge

            self.agent_bridge = AgentMemoryBridge(
                agent_memory_root=None,
                project_root=_get_core_project_root(),
            )
            if self.agent_bridge.enabled:
                stats = self.agent_bridge.get_stats()
                logger.info(f"[Agent桥接] 已连接 | 笔记数={stats.get('total_notes', 0)}")
            self.retrieval.agent_bridge = self.agent_bridge
        except Exception as e:
            logger.debug(f"[Agent桥接] 初始化跳过: {e}")

        # Cleanup legacy files
        try:
            from .cleanup import cleanup_legacy_files as _cleanup

            cs = _cleanup(base_dir=self._config.base_dir)
            if cs.get("success") and sum(len(cs.get(k, [])) for k in ("deleted_files", "deleted_dirs")) > 0:
                logger.info("[清理] 已删除旧格式记忆文件")
        except Exception:
            pass

        self.enabled = True
        self.current_emotion = "neutral"
        self._turns_since_persist = 0
        self._last_persist_at = time.time()
        self._warm_working_memory_from_recent_episodes(max_turns=self._config.working_warmup_turns)

        logger.info("=" * 60)
        logger.info("HumanMemoryEngine (Engram) 已初始化")
        logger.info(f"  数据目录: {self._config.base_dir}")
        logger.info(f"  C++加速: {bool(self.memory_cpp_backend)}")
        logger.info(f"  Engram槽位: {self.engram.total_slots_used}")
        logger.info(f"  工作记忆容量: {self._config.working_capacity}")
        logger.info(f"  语义事实: {self.semantic.count()}")
        logger.info(f"  情景事件: {self.episodic.count()}")
        logger.info("=" * 60)

    # ===================================================================
    # Public API — these are the methods used by memory_service/main.py
    # ===================================================================

    def store(self, content: str, metadata: Optional[dict] = None) -> str:
        """Store interaction content. Returns status string."""
        user_text, ai_text = self._parse_interaction(content)
        if not user_text or not ai_text:
            return "ignored-empty"

        user_id = self._normalize_user_id((metadata or {}).get("user_id"))
        disable_fact_extraction = bool((metadata or {}).get("disable_fact_extraction", False))
        deferred_persist = bool((metadata or {}).get("deferred_persist", False))
        self.record_interaction(
            user_text,
            ai_text,
            user_id=user_id,
            enable_fact_extraction=not disable_fact_extraction,
            immediate_persist=not deferred_persist,
        )
        return "stored"

    def retrieve(self, query: str, n_results: int = 5, user_id: Optional[str] = None) -> str:
        """Retrieve relevant memories as formatted context string."""
        scoped_user_id = self._normalize_user_id(user_id)
        if not query or not self.enabled:
            return self.working.get_context_string(user_id=scoped_user_id)
        return self.retrieval.multi_strategy_recall(query, n_results=n_results, user_id=scoped_user_id)

    def record_interaction(
        self,
        user_text: str,
        ai_text: str,
        user_id: str = "",
        enable_fact_extraction: bool = True,
        immediate_persist: bool = True,
    ):
        """
        Record one conversation turn through full pipeline.

        Pipeline:
          1. Working memory buffer
          2. Engram store (O(1) hash-addressed)
          3. Fact extraction from user text → SemanticMemory
          4. Episode log → EpisodicMemory
        """
        user_text = (user_text or "").strip()
        ai_text = (ai_text or "").strip()
        if not user_text or not ai_text:
            return

        scoped_user_id = self._normalize_user_id(user_id)

        with self._lock:
            # Step 1: Working memory
            self.working.add_turn(
                user_text=user_text,
                ai_text=ai_text,
                metadata={"user_id": scoped_user_id} if scoped_user_id else {},
            )

            combined = f"{user_text} {ai_text}"

            # Step 2: Engram store — O(1) hash-addressed long-term memory
            # Only store USER input (not AI reply) to prevent self-poisoning
            self.engram.store(
                text=user_text,
                source="user_input",
                confidence=0.7,
                metadata={
                    "type": "interaction",
                    "user_id": scoped_user_id,
                },
            )

            # Step 3: LLM fact extraction → semantic facts
            extracted_facts: list[dict] = []
            if enable_fact_extraction and self._llm_extract_fn:
                try:
                    result = self._llm_extract_fn(
                        f"从以下用户话语中提取关于用户的事实信息。返回JSON格式。\n用户话语: {user_text}"
                    )
                    if isinstance(result, dict):
                        facts_list = result.get("facts", [])
                        if isinstance(facts_list, list):
                            extracted_facts = facts_list
                except Exception as e:
                    logger.debug(f"LLM事实提取失败(非致命): {e}")

            for fact_data in extracted_facts:
                if isinstance(fact_data, dict):
                    fact_text = fact_data.get("fact", "") or fact_data.get("content", "")
                    category = fact_data.get("category", "general") or "general"
                    confidence = fact_data.get("confidence", 0.75)
                    if fact_text:
                        self.semantic.upsert(
                            content=fact_text,
                            category=category,
                            confidence=min(max(float(confidence), 0.1), 1.0),
                            source="extracted_from_interaction",
                            metadata={"user_id": scoped_user_id} if scoped_user_id else {},
                        )

            # Step 4: Episode log
            self.episodic.add_episode(
                user_input=user_text,
                assistant_output=ai_text,
                metadata={
                    "type": "conversation",
                    "facts_extracted": len(extracted_facts),
                    "user_id": scoped_user_id,
                },
            )

            # Step 5: Persistence (immediate for strict durability, deferred for batch throughput)
            self._persist_if_needed(force=immediate_persist)

        logger.debug(f"[交互记录] user='{user_text[:40]}...' | facts={len(extracted_facts)}")

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
            self._turns_since_persist = 0
            self._last_persist_at = now
        except Exception as e:
            logger.warning(f"[持久化] 写入异常(非致命): {e}")

    def _warm_working_memory_from_recent_episodes(self, max_turns: int = 4) -> None:
        if max_turns <= 0:
            return
        try:
            recent = self.episodic.get_recent(n=max_turns)
            if not recent:
                return
            for ep in recent:
                user_text = (ep.user_input or "").strip()
                ai_text = (ep.assistant_output or "").strip()
                if not user_text or not ai_text:
                    continue
                episode_user_id = self._normalize_user_id((ep.metadata or {}).get("user_id"))
                self.working.add_turn(
                    user_text=user_text,
                    ai_text=ai_text,
                    metadata={
                        "source": "episodic_warmup",
                        "user_id": episode_user_id,
                    } if episode_user_id else {"source": "episodic_warmup"},
                    timestamp=ep.timestamp,
                )
        except Exception as exc:
            logger.debug(f"[工作记忆预热] 跳过: {exc}")

    @staticmethod
    def _parse_interaction(content: str) -> tuple[str, str]:
        text = (content or "").replace("\\n", "\n").strip()
        if not text:
            return "", ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        prompt, output = "", ""

        for line in lines:
            if line.startswith(("用户", "User")) and not prompt:
                for sep in ("用户:", "User:", "用户："):
                    if sep in line or sep.lower() in line:
                        prompt = line.split(sep, 1)[-1].strip()
                        break
            elif line.startswith(("AI", "Assistant")) and not output:
                for sep in ("AI:", "Assistant:", "AI："):
                    if sep in line or sep.lower() in line:
                        output = line.split(sep, 1)[-1].strip()
                        break

        if not prompt and len(lines) == 1:
            prompt = lines[0]
        return prompt.strip(), output.strip()

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    def stats(self) -> dict[str, Any]:
        """Return comprehensive statistics."""
        return {
            "engine_uptime_seconds": time.time() - self._init_time,
            "enabled": self.enabled,
            "memory_cpp_accel_enabled": bool(self.memory_cpp_backend),
            "memory_cpp_accel_library": getattr(self.memory_cpp_backend, "library_path", ""),
            "working_memory_count": self.working.size,
            "working_memory_capacity": self._config.working_capacity,
            "engram_total_slots_used": self.engram.total_slots_used,
            "semantic_facts_active": self.semantic.count(),
            "episodic_events": self.episodic.count(),
            "current_emotion": self.current_emotion,
        }

    def close(self):
        """Persist everything to disk."""
        with self._lock:
            try:
                self.engram.save()
                self.semantic.save()
                self.episodic.save()
                self.retrieval.clear_cache()
                logger.info("[关闭] 所有记忆已持久化到磁盘")
            except Exception as e:
                logger.error(f"[关闭] 持久化失败: {e}")

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
        if not new_info.strip():
            return False
        try:
            with self._lock:
                self.semantic.upsert(
                    content=new_info.strip(),
                    category="manual_correction",
                    confidence=0.98,
                    source="force_update",
                )
            logger.info(f"[强制更新] 注入更正记忆: {new_info[:50]}...")
            return True
        except Exception as e:
            logger.error(f"[强制更新] 失败: {e}")
            return False

    def clear_about(self, keyword: str) -> int:
        """Deactivate memories matching a keyword."""
        count = 0
        try:
            with self._lock:
                count += self.semantic.deactivate_matching(keyword)
                count += self.episodic.deactivate_matching(keyword)
            logger.info(f"[清除记忆] 关键词 '{keyword}', 清除 {count} 条")
        except Exception as e:
            logger.error(f"[清除记忆] 失败: {e}")
        return count

    def cleanup_old_memories(self):
        """Run maintenance: decay low-confidence facts, archive old episodes."""
        with self._lock:
            self.semantic.apply_decay(time.time())
            self.episodic.prune_old()

    def resolve_all_contradictions(self):
        """Detect and resolve contradictory facts in semantic memory."""
        with self._lock:
            resolved = self.semantic.resolve_contradictions()
            if resolved > 0:
                logger.info(f"[矛盾解决] 解决了 {resolved} 组矛盾事实")

    def summarize_day(self):
        """Generate daily summary of memory state."""
        s = self.stats()
        logger.info(
            f"[每日总结] 工作记忆={s['working_memory_count']} | "
            f"活跃事实={s['semantic_facts_active']} | "
            f"情景事件={s['episodic_events']}"
        )
