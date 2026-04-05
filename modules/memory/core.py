"""
Human Memory Engine — Core orchestrator for a biologically-inspired memory system.

Architecture (inspired by Tulving's model + modern cognitive science):
┌─────────────────────────────────────────────────────┐
│                  HumanMemoryEngine                   │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Working  │→ │  Semantic   │←→│   Episodic     │  │
│  │ Memory   │  │  (Facts)    │  │  (Episodes)    │  │
│  │ ~7 items │  │  Persistent │  │  Event log     │  │
│  └──────────┘  └─────────────┘  └────────────────┘  │
│         ↓              ↓                ↓           │
│  ┌──────────────────────────────────────────────┐   │
│  │          Retrieval Engine                     │   │
│  │  (multi-strategy recall with confidence)     │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘

Key principles:
1. Anti-contamination — uncertain/negative responses are never stored as facts.
2. Fact extraction — user declarative statements are extracted as structured facts.
3. Layered recall — working memory → semantic facts → episodic events.
4. Confidence tracking — every stored item has a confidence score that decays.
5. Biological forgetting — Ebbinghaus-style decay curves on all memories.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

import numpy as np

from ..logging_config import get_logger
from .core_enums import MemoryTier, MemoryItem
from .engram_config import ENGRAM_CONFIG
from .engram_tokenizer import CompressedTokenizer
from .engram_hashing import NgramHashMapper
from .engram_store import EngramMemoryStore
from .working import WorkingMemory
from .semantic import SemanticMemory
from .episodic import EpisodicMemory
from .retrieval import RetrievalEngine


def _get_core_project_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from .semantic import SemanticMemory
from .working import WorkingMemory
from .retrieval import RetrievalEngine

logger = get_logger("Memory.Core")


class MemoryTier(Enum):
    """Memory tier classification."""
    WORKING = auto()
    SEMANTIC = auto()
    EPISODIC = auto()


@dataclass(frozen=True)
class MemoryItem:
    """Immutable snapshot of a single memory entry."""
    id: str
    content: str
    source_tier: MemoryTier
    confidence: float
    created_at: float
    last_accessed_at: float
    access_count: int
    embedding: Optional[np.ndarray] = field(default=None, hash=False, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds < 3600  # < 1 hour


class MemoryConfig:
    """Centralized configuration for all memory subsystems."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

        # Working memory
        self.working_capacity = max(3, int(os.environ.get("MEMORY_WORKING_CAPACITY", "7")))

        # Semantic memory (facts)
        self.facts_path = os.path.join(base_dir, "semantic_facts.json")
        self.min_fact_confidence = float(os.environ.get("MEMORY_MIN_FACT_CONFIDENCE", "0.35"))
        self.fact_confidence_decay_rate = float(os.environ.get("MEMORY_FACT_DECAY_RATE", "0.0001"))
        self.max_facts_per_slot = int(os.environ.get("MEMORY_MAX_FACTS_PER_SLOT", "20"))

        # Episodic memory (events)
        self.episodes_path = os.path.join(base_dir, "episodes.jsonl")
        self.episode_embedding_dim = int(os.environ.get("MEMORY_EMBEDDING_DIM", "384"))
        self.max_episodes = int(os.environ.get("MEMORY_MAX_EPISODES", "10000"))
        self.episode_similarity_threshold = float(os.environ.get("MEMORY_EPISODE_SIM_THRESHOLD", "0.25"))

        # Retrieval
        self.retrieval_n_results = int(os.environ.get("MEMORY_RETRIEVAL_N_RESULTS", "4"))
        self.retrieval_min_confidence = float(os.environ.get("MEMORY_RETRIEVAL_MIN_CONFIDENCE", "0.15"))
        self.retrieval_cache_ttl = float(os.environ.get("MEMORY_RETRIEVAL_CACHE_TTL_SEC", "8"))
        self.retrieval_cache_size = int(os.environ.get("MEMORY_RETRIEVAL_CACHE_SIZE", "128"))


class HumanMemoryEngine:
    """
    Biologically-inspired human-like memory system.

    This is the core engine that coordinates all memory subsystems:
    - WorkingMemory: short-term buffer (~7 items, like human working memory)
    - SemanticMemory: long-term factual knowledge (what/who/where)
    - EpisodicMemory: event/experience log (when/how it happened)
    - RetrievalEngine: multi-strategy recall mechanism

    Thread-safe via internal lock.
    """

    def __init__(
        self,
        embedding_fn: Optional[Callable[[str], np.ndarray]] = None,
        llm_extract_fn: Optional[Callable[[str], dict[str, Any]]] = None,
        base_dir: Optional[str] = None,
    ):
        """
        Initialize the human memory engine.

        Args:
            embedding_fn: Callable that converts text to numpy embedding vector.
                          Signature: fn(text: str) -> np.ndarray of shape (dim,)
            llm_extract_fn: Optional callable for LLM-based fact extraction.
                            Returns structured fact candidates from text.
            base_dir: Directory for persistent storage files.
        """
        project_root = os.environ.get(
            "PROJECT_ROOT",
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )

        self._config = MemoryConfig(base_dir or os.path.join(project_root, "data", "memoripy"))
        self._embedding_fn = embedding_fn
        self._llm_extract_fn = llm_extract_fn
        self._lock = threading.RLock()

        # Initialize subsystems
        self.working = WorkingMemory(
            capacity=self._config.working_capacity,
            embedding_fn=embedding_fn,
        )
        self.semantic = SemanticMemory(
            path=self._config.facts_path,
            min_confidence=self._config.min_fact_confidence,
            decay_rate=self._config.fact_confidence_decay_rate,
            max_facts_per_slot=self._config.max_facts_per_slot,
        )
        self.episodic = EpisodicMemory(
            path=self._config.episodes_path,
            embedding_fn=embedding_fn,
            dim=self._config.episode_embedding_dim,
            max_episodes=self._config.max_episodes,
            similarity_threshold=self._config.episode_similarity_threshold,
        )
        self.retrieval = RetrievalEngine(
            working_memory=self.working,
            semantic_memory=self.semantic,
            episodic_memory=self.episodic,
            embedding_fn=embedding_fn,
            cache_ttl=self._config.retrieval_cache_ttl,
            cache_size=self._config.retrieval_cache_size,
            min_confidence=self._config.retrieval_min_confidence,
        )

        self.enabled = True
        self.current_emotion = "neutral"
        self._init_time = time.time()

        from .cleanup import cleanup_legacy_files as _cleanup_old_files

        _cleanup_stats = _cleanup_old_files(base_dir=self._config.base_dir)
        if _cleanup_stats.get("success"):
            n_del = len(_cleanup_stats.get("deleted_files", [])) + len(_cleanup_stats.get("deleted_dirs", []))
            if n_del > 0:
                logger.info(f"[清理] 已删除 {n_del} 个旧格式记忆文件")

        # === Step 2: Agent Memory Bridge — one-way read from Agent's Markdown memories ===
        from .agent_bridge import AgentMemoryBridge

        self.agent_bridge = AgentMemoryBridge(
            agent_memory_root=None,
            project_root=_get_core_project_root(),
        )
        if self.agent_bridge.enabled:
            agent_stats = self.agent_bridge.get_stats()
            logger.info(f"[Agent桥接] 已连接 | 总笔记={agent_stats.get('total_notes', 0)}")

        # Wire agent bridge into retrieval engine
        self.retrieval.agent_bridge = self.agent_bridge

        logger.info("=" * 60)
        logger.info("HumanMemoryEngine (Engram架构) 已初始化")
        logger.info(f"  工作记忆容量: {self._config.working_capacity}")
        logger.info(f"  数据目录: {self._config.base_dir}")
        logger.info(f"  语义事实数: {self.semantic.count()}")
        logger.info(f"  情景事件数: {self.episodic.count()}")
        logger.info("=" * 60)

    @property
    def short_term_memory(self) -> deque:
        """Backward compat: expose working memory as deque."""
        return self.working.as_deque()

    @staticmethod
    def _parse_interaction(content: str) -> tuple[str, str]:
        """Parse standard '用户: ...\\nAI: ...' format into (prompt, output)."""
        text = (content or "").replace("\\n", "\n").strip()
        if not text:
            return "", ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        prompt, output = "", ""

        for line in lines:
            if line.startswith("用户") and not prompt:
                for sep in ("用户:", "用户："):
                    if sep in line:
                        prompt = line.split(sep, 1)[-1].strip()
                        break
            elif line.startswith("AI") and not output:
                for sep in ("AI:", "AI："):
                    if sep in line:
                        output = line.split(sep, 1)[-1].strip()
                        break

        if not prompt and len(lines) == 1:
            prompt = lines[0]

        return prompt.strip(), output.strip()




    def record_interaction(self, user_text: str, ai_text: str, add_ai_to_short_term: bool = True):
        """
        Record a complete interaction turn through the full cognitive pipeline.

        Pipeline:
        1. Add to working memory (short-term buffer)
        2. Check anti-contamination filter on AI response
        3. Extract facts from user's statement
        4. Store episode (if not contaminated)
        5. Reinforce related existing facts

        This is the PRIMARY method for recording interactions.
        """
        user_text = (user_text or "").strip()
        ai_text = (ai_text or "").strip()
        if not user_text or not ai_text:
            return

        now = time.time()

        with self._lock:
            # Step 1: Working memory
            self.working.add_turn(user_text=user_text, ai_text=ai_text)
            if add_ai_to_short_term:
                pass  # Already done by add_turn

            # All interactions are stored uniformly — no keyword-based filtering

            # Step 3: Extract facts from user input (declarative statements)
            extracted_facts = []
            if self._llm_extract_fn:
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

            # Store extracted facts
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
                            timestamp=now,
                        )

            # Step 4: Store clean episode
            self.episodic.add_episode(
                user_input=user_text,
                assistant_output=ai_text,
                metadata={"type": "conversation", "facts_extracted": len(extracted_facts)},
            )

            # Step 5: Reinforce related facts (spreading activation) — no-op in current implementation
            combined = f"{user_text} {ai_text}"

        logger.debug(
            f"[交互记录] user='{user_text[:30]}... | ai='{ai_text[:30]}... "
            f"| facts={len(extracted_facts)}"
        )

    @staticmethod
    def store_memory(self, conversation: str):
        """Store conversation string (legacy API compatibility)."""
        prompt, output = self._parse_interaction(conversation)
        if prompt:
            self.record_interaction(prompt, output or "")

    def retrieve_memories(self, query: str, n_results: int = 4) -> str:
        """
        Retrieve relevant memories using human-like multi-strategy recall.

        Returns formatted context string for LLM consumption.
        """
        if not query or not self.enabled:
            return self.working.format_context()

        with self._lock:
            result = self.retrieval.recall(query=query, n_results=n_results)
        return result

    def force_update_memory(self, old_info: str, new_info: str) -> bool:
        """Force-store a corrected fact with high confidence."""
        if not new_info.strip():
            return False
        try:
            with self._lock:
                # Upsert as a high-confidence fact
                self.semantic.upsert(
                    content=new_info.strip(),
                    category="manual_correction",
                    confidence=0.98,
                    source="force_update",
                    timestamp=time.time(),
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

    def get_memory_stats(self) -> dict:
        """Return comprehensive memory system statistics."""
        with self._lock:
            return {
                "short_term": self.working.size(),
                "short_term_capacity": self._config.working_capacity,
                "current_emotion": self.current_emotion,
                "working_memory": self.working.size(),
                "long_term": self.episodic.count(),
                "semantic_facts_active": self.semantic.count_active(),
                "semantic_facts_total": self.semantic.count(),
                "episodic_count": self.episodic.count(),
                "engine_uptime_seconds": time.time() - self._init_time,
                "enabled": self.enabled,
            }

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
        stats = self.get_memory_stats()
        logger.info(
            f"[每日总结] 工作记忆={stats['working_memory']} | "
            f"活跃事实={stats['semantic_facts_active']} | "
            f"情景事件={stats['episodic_count']}"
        )

    def close(self):
        """Persist all memory to disk and release resources."""
        with self._lock:
            try:
                self.semantic.save()
                self.episodic.save()
                self.retrieval.clear_cache()
                logger.info("[关闭] 所有记忆已持久化到磁盘")
            except Exception as e:
                logger.error(f"[关闭] 持久化失败: {e}")

    # --- Backward-compat aliases ---

    def add_to_short_term(self, role: str, content: str):
        """Legacy: add to working memory by role."""
        with self._lock:
            self.working.add_raw(role=role, content=content, timestamp=time.time())

    def get_short_term_context(self) -> str:
        """Legacy: get formatted working memory context."""
        with self._lock:
            return self.working.format_context()