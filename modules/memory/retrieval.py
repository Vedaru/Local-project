"""
检索模块 - 记忆检索、去重、排序
"""
import time
from concurrent.futures import as_completed

from .config import SIMILARITY_THRESHOLD
from .logger import get_logger
from .analyzers import TextAnalyzer
from .conflict import ConflictDetector

logger = get_logger()


class MemoryRetriever:
    """记忆检索器"""
    
    def __init__(self, storage):
        """
        Args:
            storage: MemoryStorage 实例
        """
        self.storage = storage
    
    def retrieve_memories(self, query: str, short_term_context: str, n_results: int = 3) -> str:
        """
        并行检索记忆（低延迟）
        
        Args:
            query: 查询文本
            short_term_context: 短期记忆上下文
            n_results: 返回结果数量
        """
        if not self.storage.enabled:
            return ""
        
        logger.debug(f"[检索] 查询: {query[:50]}...")
        
        # 并行查询所有集合
        all_memories = []
        futures = []
        executor = self.storage.get_executor()
        collections = self.storage.get_collections()
        
        for collection, layer_name in collections:
            future = executor.submit(
                self._query_collection, collection, layer_name, query, n_results
            )
            futures.append(future)
        
        # 等待所有查询完成
        for future in as_completed(futures, timeout=2.0):
            try:
                memories = future.result()
                all_memories.extend(memories)
            except Exception:
                pass
        
        if not all_memories:
            return short_term_context if short_term_context else ""
        
        # 去重（包括偏好矛盾检测）
        all_memories = self._deduplicate_memories(all_memories)
        
        # 排序：优先新记忆
        current_time = time.time()
        for mem in all_memories:
            time_score = 1.0 / (1.0 + (current_time - mem['timestamp']) / 86400)
            mem['final_score'] = mem['strength'] * 0.5 + time_score * 0.3 + (1 - mem['distance']) * 0.2
        
        all_memories.sort(key=lambda x: -x['final_score'])
        top_memories = all_memories[:n_results]
        
        # 记录检索结果
        if top_memories:
            logger.debug(f"[检索结果] 找到 {len(top_memories)} 条相关记忆")
            for mem in top_memories:
                logger.debug(f"  - [{mem['layer']}] {mem['content'][:40]}... | 距离={mem['distance']:.3f}")
        
        # 异步更新访问计数
        update_queue = self.storage.get_update_queue()
        for mem in top_memories:
            update_queue.put((mem['id'], mem['collection']))
        
        # 组装结果
        parts = []
        if short_term_context:
            parts.append(f"【最近对话】\n{short_term_context}")
        
        main_contents = [m['content'] for m in top_memories]
        if main_contents:
            parts.append(f"【相关记忆】\n" + "\n".join(main_contents))
        
        return "\n\n".join(parts)
    
    def _query_collection(self, collection, layer_name: str, query: str, n_results: int) -> list:
        """查询单个集合"""
        memories = []
        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )
            
            docs = results.get('documents', [[]])[0]
            metas = results.get('metadatas', [[]])[0]
            distances = results.get('distances', [[]])[0]
            ids = results.get('ids', [[]])[0]
            
            for doc, meta, dist, doc_id in zip(docs, metas, distances, ids):
                if dist < SIMILARITY_THRESHOLD:
                    memories.append({
                        'content': doc,
                        'layer': layer_name,
                        'distance': dist,
                        'strength': TextAnalyzer.calculate_memory_strength(meta),
                        'timestamp': meta.get('timestamp', 0),
                        'id': doc_id,
                        'collection': collection
                    })
        except Exception:
            pass
        return memories
    
    def _deduplicate_memories(self, memories: list) -> list:
        """
        去重：相似记忆只保留最新的
        特别处理偏好矛盾（喜欢 vs 不喜欢）
        """
        if len(memories) <= 1:
            return memories
        
        # 按时间戳降序排列（新的在前）
        memories.sort(key=lambda x: -x['timestamp'])
        
        result = []
        seen_contents = []
        
        for mem in memories:
            content = mem['content']
            is_duplicate = False
            
            for seen in seen_contents:
                # 检查1：偏好矛盾（同一对象的矛盾偏好）
                if ConflictDetector.is_preference_contradiction(content, seen):
                    is_duplicate = True
                    logger.debug(f"[去重] 偏好矛盾，保留新记忆: {seen[:30]}... vs {content[:30]}...")
                    break
                
                # 检查2：同类偏好更新（不同对象但同一类别的偏好）
                if ConflictDetector.is_same_category_preference(seen, content):
                    is_duplicate = True
                    logger.debug(f"[去重] 同类偏好更新，保留新记忆: {seen[:30]}... vs {content[:30]}...")
                    break
                
                # 检查3：字符相似度
                common = len(set(content) & set(seen))
                similarity = common / max(len(set(content)), len(set(seen)), 1)
                
                if similarity > 0.6:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                result.append(mem)
                seen_contents.append(content)
        
        return result
