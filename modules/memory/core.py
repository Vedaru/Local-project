"""
核心记忆管理类 - 整合所有模块
"""
import time
from collections import deque

from .config import SHORT_TERM_CAPACITY
from .logger import get_logger, get_log_path, get_log_dir
from .storage import MemoryStorage
from .retrieval import MemoryRetriever

logger = get_logger()


class HumanLikeMemory:
    """
    人类化记忆系统（模块化版本）
    
    特性：
    1. 异步存储 - 记忆存储在后台线程执行
    2. 并行检索 - 多集合并行查询
    3. 缓存热点 - LRU缓存常用数据
    4. 延迟更新 - 访问计数批量更新
    5. 智能冲突覆盖 - 新记忆自动覆盖旧的矛盾记忆
    """
    
    def __init__(self):
        # 短期记忆
        self.short_term_memory = deque(maxlen=SHORT_TERM_CAPACITY)
        self.current_emotion = 'neutral'
        self.memory_links = {}
        
        # 日志记录器
        self.logger = logger
        
        # 初始化存储层
        self._storage = MemoryStorage()
        
        # 初始化检索器
        self._retriever = MemoryRetriever(self._storage)
        
        # 向外暴露属性（向后兼容）
        self.enabled = self._storage.enabled
        self.long_term = self._storage.long_term
        self.emotional = self._storage.emotional
        self.working = self._storage.working
        self._collections = self._storage.get_collections()
    
    # ==================== 短期记忆 ====================
    
    def add_to_short_term(self, role: str, content: str):
        """添加到短期记忆"""
        self.short_term_memory.append({
            'role': role,
            'content': content,
            'timestamp': time.time()
        })
        self.logger.debug(f"[短期记忆] {role}: {content[:50]}...")
    
    def get_short_term_context(self) -> str:
        """获取短期记忆上下文"""
        if not self.short_term_memory:
            return ""
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.short_term_memory)
    
    # ==================== 存储接口 ====================
    
    def store_memory(self, conversation: str):
        """异步存储记忆（非阻塞）"""
        self.current_emotion = self._storage.store_memory(conversation, self.current_emotion)
    
    # ==================== 检索接口 ====================
    
    def retrieve_memories(self, query: str, n_results: int = 3) -> str:
        """并行检索记忆"""
        short_term_context = self.get_short_term_context()
        return self._retriever.retrieve_memories(query, short_term_context, n_results)
    
    # ==================== 维护方法 ====================
    
    def cleanup_old_memories(self):
        """清理旧记忆"""
        self._storage.cleanup_old_memories()

    def resolve_all_contradictions(self):
        """对所有记忆进行句意理解并清理矛盾对"""
        self._storage.resolve_all_contradictions()
    
    def get_memory_stats(self) -> dict:
        """获取统计信息"""
        stats = self._storage.get_stats()
        stats.update({
            'short_term': len(self.short_term_memory),
            'short_term_capacity': SHORT_TERM_CAPACITY,
            'current_emotion': self.current_emotion,
            'log_file': get_log_path()
        })
        return stats
    
    @staticmethod
    def get_log_path() -> str:
        """获取日志文件路径"""
        return get_log_path()
    
    @staticmethod
    def get_log_dir() -> str:
        """获取日志目录路径"""
        return get_log_dir()
    
    def summarize_day(self):
        """每日总结"""
        if not self._storage.enabled:
            return
        
        today_start = time.time() - 86400
        today_memories = []
        
        for collection, _ in self._collections:
            try:
                results = collection.get(include=["documents", "metadatas"])
                for doc, meta in zip(results.get('documents', []), results.get('metadatas', [])):
                    if meta and meta.get('timestamp', 0) > today_start:
                        today_memories.append({
                            'content': doc,
                            'importance': meta.get('importance', 0.5)
                        })
            except Exception:
                pass
        
        if today_memories:
            today_memories.sort(key=lambda x: -x['importance'])
            self.logger.info(f"[每日总结] 今日形成 {len(today_memories)} 条记忆")
            for i, m in enumerate(today_memories[:5], 1):
                self.logger.info(f"  {i}. {m['content'][:60]}...")
            print(f"\n[📖 每日总结] 今日形成 {len(today_memories)} 条记忆")
            for i, m in enumerate(today_memories[:3], 1):
                print(f"  {i}. {m['content'][:40]}...")
    
    def force_update_memory(self, old_info: str, new_info: str) -> bool:
        """强制更新记忆"""
        return self._storage.force_update_memory(old_info, new_info)
    
    def clear_about(self, keyword: str) -> int:
        """清除关于某个关键词的所有记忆"""
        return self._storage.clear_about(keyword)
    
    def close(self):
        """关闭记忆系统"""
        self.summarize_day()
        self._storage.close()


# 向后兼容
class MemoryManager(HumanLikeMemory):
    pass
