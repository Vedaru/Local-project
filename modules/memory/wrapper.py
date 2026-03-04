"""
MemoryManager wrapper — provides the same API as the old HumanLikeMemory/MemoryManager
on top of memoripy.

This is a drop-in replacement: main.py and other callers use the same interface.
Internally, all memory operations are delegated to memoripy's MemoryManager.
"""

import os
import time
from collections import deque
from typing import Any, Optional

from ..config import PROJECT_ROOT
from ..logging_config import get_logger
from .memoripy import JSONStorage
from .memoripy import MemoryManager as MemoripyManager
from .models import ArkChatModel, ArkEmbeddingModel, HashEmbeddingModel, LocalEmbeddingModel

logger = get_logger("Memory")

SHORT_TERM_CAPACITY = 7


class MemoryManager:
    """
    Drop-in replacement for the old HumanLikeMemory/MemoryManager.
    Backed by memoripy for persistent memory storage and retrieval.

    Features inherited from memoripy:
    - FAISS-based similarity search
    - Short-term / long-term memory classification
    - Concept graph with spreading activation
    - Semantic clustering via K-Means
    - Time-based decay and reinforcement learning
    """

    def __init__(self) -> None:
        # Short-term memory (recent conversation turns for display)
        self.short_term_memory: deque[tuple[str, str]] = deque(maxlen=SHORT_TERM_CAPACITY)
        self.current_emotion: str = "neutral"
        self.enabled: bool = False
        self._manager: Optional[MemoripyManager] = None

        # Storage path
        memory_dir = os.path.join(PROJECT_ROOT, "data", "memoripy")
        os.makedirs(memory_dir, exist_ok=True)
        history_path = os.path.join(memory_dir, "interaction_history.json")

        try:
            # Initialize models
            chat_model = ArkChatModel()
            embedding_model = self._create_embedding_model()
            storage = JSONStorage(history_path)

            # Initialize memoripy MemoryManager
            self._manager = MemoripyManager(
                chat_model=chat_model,
                embedding_model=embedding_model,
                storage=storage,
            )
            self.enabled = True

            # Log stats
            store = self._manager.memory_store
            logger.info("=" * 50)
            logger.info("memoripy 记忆系统已初始化")
            logger.info(f"存储路径: {history_path}")
            logger.info(f"嵌入维度: {self._manager.dimension}")
            logger.info(f"短期记忆: {len(store.short_term_memory)} 条")
            logger.info(f"长期记忆: {len(store.long_term_memory)} 条")
            logger.info(f"概念图节点: {store.graph.number_of_nodes()}")
            logger.info("记忆系统已就绪")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"记忆系统初始化失败: {e}", exc_info=True)
            self._manager = None
            self.enabled = False

    @staticmethod
    def _create_embedding_model() -> Any:
        """创建嵌入模型：优先 Ark API → 本地哈希嵌入 → 本地 sentence-transformers。"""
        # 1. 尝试 Ark API 嵌入模型（需要 EMBEDDING_MODEL_NAME 配置）
        try:
            model = ArkEmbeddingModel()
            logger.info("使用 Ark API 嵌入模型")
            return model
        except Exception as e:
            logger.warning(f"Ark 嵌入模型不可用: {e}")

        # 2. 本地哈希嵌入（无需任何下载，即开即用）
        try:
            model = HashEmbeddingModel()
            logger.info("使用本地轻量哈希嵌入模型（无需网络）")
            return model
        except Exception as e:
            logger.warning(f"本地哈希嵌入模型不可用: {e}")

        # 3. 最终回退：本地 sentence-transformers（需要下载模型）
        try:
            model = LocalEmbeddingModel()
            logger.info("使用本地 sentence-transformers 嵌入模型")
            return model
        except Exception as e:
            logger.warning(f"本地 sentence-transformers 不可用: {e}")

        raise RuntimeError("无法初始化任何嵌入模型")

    # ==================== 短期记忆 ====================

    def add_to_short_term(self, role: str, content: str):
        """添加到短期记忆（最近对话轮次）"""
        self.short_term_memory.append({"role": role, "content": content, "timestamp": time.time()})
        logger.debug(f"[短期记忆] {role}: {content[:50]}...")

    def get_short_term_context(self) -> str:
        """获取短期记忆上下文"""
        if not self.short_term_memory:
            return ""
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.short_term_memory)

    # ==================== 存储接口 ====================

    def store_memory(self, conversation: str):
        """
        存储对话到 memoripy 的持久化记忆。

        Args:
            conversation: 格式为 "用户: ...\nAI: ..." 的对话字符串
        """
        if not self.enabled or not self._manager:
            return

        try:
            # Parse conversation string into prompt and output
            prompt = conversation
            output = ""
            if "\n" in conversation:
                lines = conversation.split("\n", 1)
                first_line = lines[0].strip()
                second_line = lines[1].strip() if len(lines) > 1 else ""
                # Try to extract user/AI parts
                if first_line.startswith("用户:") or first_line.startswith("用户："):
                    prompt = first_line.split(":", 1)[-1].split("：", 1)[-1].strip()
                else:
                    prompt = first_line
                if second_line.startswith("AI:") or second_line.startswith("AI："):
                    output = second_line.split(":", 1)[-1].split("：", 1)[-1].strip()
                else:
                    output = second_line

            if not prompt or len(prompt) < 2:
                return

            # Get embedding and concepts
            combined = f"{prompt} {output}" if output else prompt
            embedding = self._manager.get_embedding(combined)
            concepts = self._manager.extract_concepts(combined)

            # Store interaction
            self._manager.add_interaction(prompt, output, embedding, concepts)
            logger.debug(f"[存储] {prompt[:40]}... | 概念={concepts[:3]}")

        except Exception as e:
            logger.error(f"记忆存储失败: {e}")

    # ==================== 检索接口 ====================

    def retrieve_memories(self, query: str, n_results: int = 3) -> str:
        """
        检索与查询相关的记忆上下文。

        Args:
            query: 用户输入查询
            n_results: 返回结果数量

        Returns:
            格式化的记忆上下文字符串
        """
        if not self.enabled or not self._manager:
            short_term = self.get_short_term_context()
            return short_term if short_term else ""

        try:
            # Retrieve relevant interactions from memoripy
            relevant = self._manager.retrieve_relevant_interactions(
                query, exclude_last_n=min(5, len(self._manager.memory_store.short_term_memory))
            )

            parts = []
            short_term = self.get_short_term_context()
            if short_term:
                parts.append(f"【最近对话】\n{short_term}")

            if relevant:
                memory_lines = []
                for r in relevant[:n_results]:
                    p = r.get("prompt", "")
                    o = r.get("output", "")
                    if p and o:
                        memory_lines.append(f"用户: {p}\nAI: {o}")
                    elif p:
                        memory_lines.append(f"用户: {p}")
                if memory_lines:
                    parts.append("【相关记忆】\n" + "\n".join(memory_lines))

            result = "\n\n".join(parts)
            if result:
                logger.debug(f"[检索] 返回 {len(relevant)} 条相关记忆")
            return result

        except Exception as e:
            logger.error(f"记忆检索失败: {e}")
            return self.get_short_term_context()

    # ==================== 维护方法 ====================

    def cleanup_old_memories(self):
        """清理/分类旧记忆"""
        if not self._manager:
            return
        try:
            self._manager.memory_store.classify_memory()
            logger.info("记忆清理/分类完成")
        except Exception as e:
            logger.error(f"记忆清理失败: {e}")

    def resolve_all_contradictions(self):
        """memoripy 模式下暂无矛盾检测（占位）"""
        pass

    def get_memory_stats(self) -> dict:
        """获取记忆系统统计信息"""
        stats = {
            "short_term": len(self.short_term_memory),
            "short_term_capacity": SHORT_TERM_CAPACITY,
            "current_emotion": self.current_emotion,
            "working_memory": 0,
            "long_term": 0,
            "emotional": 0,
            "concept_nodes": 0,
        }
        if self._manager:
            store = self._manager.memory_store
            stats["working_memory"] = len(store.short_term_memory)
            stats["long_term"] = len(store.long_term_memory)
            stats["concept_nodes"] = store.graph.number_of_nodes()
        return stats

    def summarize_day(self):
        """每日总结"""
        if not self._manager:
            return
        store = self._manager.memory_store
        total = len(store.short_term_memory) + len(store.long_term_memory)
        logger.info(
            f"[每日总结] 总交互数: {total} (短期={len(store.short_term_memory)}, 长期={len(store.long_term_memory)})"
        )

    def force_update_memory(self, old_info: str, new_info: str) -> bool:
        """强制更新记忆（memoripy 模式下存储新记忆作为更正）"""
        if not self.enabled:
            return False
        try:
            self.store_memory(f"用户: 更正信息 - {new_info}\nAI: 好的，我已记住。")
            logger.info(f"[强制更新] 旧: {old_info} -> 新: {new_info}")
            return True
        except Exception:
            return False

    def clear_about(self, keyword: str) -> int:
        """清除关于某个关键词的记忆（memoripy 模式下目前不支持精确删除）"""
        logger.warning(f"[清除记忆] memoripy 模式暂不支持精确删除，关键词: {keyword}")
        return 0

    def close(self):
        """保存并关闭记忆系统"""
        if self._manager:
            try:
                self._manager.save_memory_to_history()
                logger.info("[关闭] 记忆已保存")
            except Exception as e:
                logger.error(f"[关闭] 保存失败: {e}")

    # ==================== 向后兼容 ====================

    @property
    def _storage(self):
        """Legacy accessor — SkillManager no longer depends on this."""
        return None

    # ==================== 异步接口 ====================

    async def add_to_short_term_async(self, role: str, content: str):
        """异步版 add_to_short_term。"""
        import asyncio

        await asyncio.to_thread(self.add_to_short_term, role, content)

    async def retrieve_memories_async(self, query: str, n_results: int = 3) -> str:
        """异步版 retrieve_memories。"""
        import asyncio

        return await asyncio.to_thread(self.retrieve_memories, query, n_results)

    async def store_memory_async(self, conversation: str):
        """异步版 store_memory。"""
        import asyncio

        await asyncio.to_thread(self.store_memory, conversation)

    async def get_memory_stats_async(self) -> dict:
        """异步版 get_memory_stats。"""
        import asyncio

        return await asyncio.to_thread(self.get_memory_stats)
