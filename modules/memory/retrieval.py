"""
检索模块 - 记忆检索、去重、排序
"""
import time
from concurrent.futures import as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError

from .config import SIMILARITY_THRESHOLD, PREFERENCE_PATTERNS
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

        def is_review_question(text: str) -> bool:
            review_patterns = [
                '你还记得', '还记得我', '我之前说过', '我以前说过', '我刚才说', '我刚刚说',
                '我曾经说', '我刚才提到', '我刚刚提到', '我之前提到', '我以前提到',
                '你记得', '记得我', '你能回忆', '你能想起', '你能记得', '你能告诉我我',
                '我问过', '我说过', '我提过', '我提到过', '我讲过', '我讲到过',
                '你知道我', '你知道我喜欢', '你知道我讨厌', '你知道我最喜欢', '你知道我最讨厌',
            ]
            return any(p in text for p in review_patterns)

        def extract_user_input(text: str) -> str:
            return self._extract_user_input(text)

        def is_preference_memory(text: str) -> bool:
            return self._is_preference_memory(text)

        review_question = is_review_question(query)
        
        # 并行查询所有集合
        all_memories = []
        futures = []
        executor = self.storage.get_executor()
        collections = self.storage.get_collections()

        # 回顾性提问：使用同步元数据检索，避免超时
        if review_question:
            user_input = extract_user_input(query)
            category = ConflictDetector.get_preference_category(user_input)
            
            # 1. 先尝试按类别检索偏好（如果有明确类别）
            if category:
                metadata_results = self._query_preference_metadata(category=category, n_results=30)
                if metadata_results:
                    all_memories.extend(metadata_results)
            
            # 2. 若无结果，检索所有偏好记忆（不限类别）
            if not all_memories:
                metadata_results = self._query_preference_metadata(category=None, n_results=30)
                if metadata_results:
                    all_memories.extend(metadata_results)
            
            # 3. 最后兜底：基础向量检索
            if not all_memories:
                for collection, layer_name in collections:
                    try:
                        memories = self._query_collection(collection, layer_name, query, n_results)
                        all_memories.extend(memories)
                    except Exception:
                        pass
        else:
            # 非回顾性提问：正常并行检索
            for collection, layer_name in collections:
                future = executor.submit(
                    self._query_collection, collection, layer_name, query, n_results
                )
                futures.append(future)
        
        # 等待所有查询完成
        try:
            for future in as_completed(futures, timeout=5.0):
                try:
                    memories = future.result()
                    all_memories.extend(memories)
                except Exception:
                    pass
        except FuturesTimeoutError:
            logger.debug(f"[检索超时] 未完成任务: {len([f for f in futures if not f.done()])}")
            for future in futures:
                if future.done():
                    try:
                        memories = future.result()
                        all_memories.extend(memories)
                    except Exception:
                        pass
        
        if not all_memories:
            return short_term_context if short_term_context else ""
        
        # 去重（包括偏好矛盾检测）
        all_memories = self._deduplicate_memories(all_memories)

        # 回顾性提问时只返回偏好记忆
        if review_question:
            preference_memories = [m for m in all_memories if is_preference_memory(m['content'])]
            if preference_memories:
                all_memories = preference_memories
            else:
                # 回顾性提问但没有相关偏好记忆，返回空
                return short_term_context if short_term_context else ""
        
        # 排序：优先新记忆与最新同类偏好
        category_latest_ts = {}
        for mem in all_memories:
            if is_preference_memory(mem['content']):
                user_text = extract_user_input(mem['content'])
                category = ConflictDetector.get_preference_category(user_text)
                if category:
                    category_latest_ts[category] = max(category_latest_ts.get(category, 0), mem['timestamp'])

        current_time = time.time()
        for mem in all_memories:
            time_score = 1.0 / (1.0 + (current_time - mem['timestamp']) / 86400)
            preference_bonus = 0.25 if is_preference_memory(mem['content']) else 0.0
            if review_question:
                preference_bonus += 0.15
            if is_preference_memory(mem['content']):
                user_text = extract_user_input(mem['content'])
                category = ConflictDetector.get_preference_category(user_text)
                if category and mem['timestamp'] >= category_latest_ts.get(category, 0):
                    preference_bonus += 0.2
            mem['final_score'] = mem['strength'] * 0.45 + time_score * 0.25 + (1 - mem['distance']) * 0.2 + preference_bonus
        
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

    def _query_preference_metadata(self, category: str = None, n_results: int = 30) -> list:
        """基于偏好元数据检索记忆（用于回顾性提问）"""
        memories = []
        
        # ChromaDB where 语法：多条件需要 $and
        if category:
            where = {"$and": [{"preference": True}, {"preference_category": category}]}
        else:
            where = {"preference": True}

        for collection, layer_name in self.storage.get_collections():
            try:
                results = collection.get(
                    where=where,
                    limit=n_results,
                    include=["documents", "metadatas"]  # ids 默认返回，无需指定
                )

                docs = results.get('documents', [])
                metas = results.get('metadatas', [])
                ids = results.get('ids', [])
                
                logger.debug(f"[元数据检索] collection={layer_name} | where={where} | 命中={len(docs)}条")

                for doc, meta, doc_id in zip(docs, metas, ids):
                    memories.append({
                        'content': doc,
                        'layer': layer_name,
                        'distance': 1.0,
                        'strength': TextAnalyzer.calculate_memory_strength(meta or {}),
                        'timestamp': (meta or {}).get('timestamp', 0),
                        'id': doc_id,
                        'collection': collection
                    })
            except Exception as e:
                logger.debug(f"[元数据检索异常] {layer_name}: {e}")

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
                # 先检查完全相同
                if content == seen:
                    is_duplicate = True
                    break
                
                # 检查字符相似度（快速过滤）
                common = len(set(content) & set(seen))
                similarity = common / max(len(set(content)), len(set(seen)), 1)
                
                if similarity > 0.9:
                    # 极高相似度，直接跳过
                    is_duplicate = True
                    break
                elif similarity > 0.6:
                    # 中等相似度，可能是重复
                    is_duplicate = True
                    break
                
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
            
            if not is_duplicate:
                result.append(mem)
                seen_contents.append(content)
        
        # 偏好记忆按实体 + 类别去重（优先保留否定偏好）
        return self._deduplicate_preference_entities(result)

    @staticmethod
    def _extract_user_input(text: str) -> str:
        if '用户:' in text:
            return text.split('用户:')[1].split('AI:')[0].strip()
        return text

    @staticmethod
    def _get_preference_polarity(text: str) -> str:
        """返回 positive / negative / None"""
        if any(p in text for p in PREFERENCE_PATTERNS['negative']):
            return 'negative'
        if any(p in text for p in PREFERENCE_PATTERNS['positive']):
            return 'positive'
        return None

    @classmethod
    def _is_preference_memory(cls, text: str) -> bool:
        user_text = cls._extract_user_input(text)
        return ConflictDetector.detect_preference_conflict(user_text)

    def _deduplicate_preference_entities(self, memories: list) -> list:
        """
        按实体 + 类别去重，仅保留最新一条；同一实体优先否定偏好
        """
        if len(memories) <= 1:
            return memories

        preference_candidates = []
        others = []

        for mem in memories:
            if self._is_preference_memory(mem['content']):
                preference_candidates.append(mem)
            else:
                others.append(mem)

        if not preference_candidates:
            return memories

        selected_by_key = {}

        for mem in preference_candidates:
            user_text = self._extract_user_input(mem['content'])
            category = ConflictDetector.get_preference_category(user_text)
            entities = TextAnalyzer.extract_noun_entities(user_text)
            polarity = self._get_preference_polarity(user_text)

            if not entities:
                others.append(mem)
                continue

            for entity in entities:
                key = (category, entity)
                existing = selected_by_key.get(key)
                if not existing:
                    selected_by_key[key] = (mem, polarity)
                    continue

                existing_mem, existing_polarity = existing

                # 优先保留否定偏好
                if polarity == 'negative' and existing_polarity != 'negative':
                    selected_by_key[key] = (mem, polarity)
                    continue
                if existing_polarity == 'negative' and polarity != 'negative':
                    continue

                # 偏好极性一致时保留最新
                if mem['timestamp'] > existing_mem['timestamp']:
                    selected_by_key[key] = (mem, polarity)

        selected = {}
        for mem, _polarity in selected_by_key.values():
            selected[mem['id']] = mem

        return others + list(selected.values())
