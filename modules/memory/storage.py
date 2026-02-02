"""
存储层 - ChromaDB 交互、异步存储
"""
import os
import time
import uuid
import json
import queue
import threading
import chromadb
from concurrent.futures import ThreadPoolExecutor

from ..config import data_dir
from .config import STRONG_SIMILARITY_THRESHOLD, PREFERENCE_PATTERNS
from .logger import get_logger, get_log_path
from .analyzers import TextAnalyzer
from .conflict import ConflictResolver, ConflictDetector, extract_user_input

logger = get_logger()


class MemoryStorage:
    """记忆存储管理器"""
    
    def __init__(self):
        self.enabled = False
        self.long_term = None
        self.emotional = None
        self.working = None
        self._collections = []
        self._conflict_resolver = None
        
        # 异步存储队列
        self._store_queue = queue.Queue()
        self._update_queue = queue.Queue()
        
        # 线程池（增加worker数量以支持并行查询）
        self._executor = ThreadPoolExecutor(max_workers=10)
        
        self._initialize_storage()
    
    def _initialize_storage(self):
        """初始化 ChromaDB 存储"""
        os.makedirs(data_dir, exist_ok=True)
        
        logger.info("=" * 50)
        logger.info("人类化记忆系统 正在初始化（低延迟模式）")
        
        try:
            self.client = chromadb.PersistentClient(path=data_dir)
            
            self.long_term = self.client.get_or_create_collection(
                name="long_term_memory",
                metadata={"description": "巩固后的长期记忆"}
            )
            self.emotional = self.client.get_or_create_collection(
                name="emotional_memory",
                metadata={"description": "带有强烈情感的记忆"}
            )
            self.working = self.client.get_or_create_collection(
                name="working_memory",
                metadata={"description": "待巩固的工作记忆"}
            )
            
            self._collections = [
                (self.emotional, "情感记忆"),
                (self.long_term, "长期记忆"),
                (self.working, "工作记忆")
            ]
            
            self._conflict_resolver = ConflictResolver(self._collections)
            self.enabled = True
            
            logger.info(f"存储路径: {data_dir}")
            logger.info(f"长期记忆: {self.long_term.count()} | 情感记忆: {self.emotional.count()} | 工作记忆: {self.working.count()}")
            logger.info(f"日志文件: {get_log_path()}")
            logger.info("记忆系统已就绪")
            
            self._start_background_workers()
            
        except Exception as e:
            logger.error(f"记忆系统初始化失败: {e}")
            self.enabled = False
        
        logger.info("=" * 50)
    
    def _start_background_workers(self):
        """启动后台工作线程"""
        self._store_thread = threading.Thread(target=self._store_worker, daemon=True)
        self._store_thread.start()
        
        self._update_thread = threading.Thread(target=self._update_worker, daemon=True)
        self._update_thread.start()
    
    def _store_worker(self):
        """后台存储线程"""
        while True:
            try:
                task = self._store_queue.get()
                if task is None:
                    logger.debug("存储线程收到退出信号")
                    break
                self._do_store_memory(*task)
                self._store_queue.task_done()
            except Exception as e:
                logger.error(f"存储线程异常: {e}")
    
    def _update_worker(self):
        """批量更新线程"""
        pending_updates = []
        last_flush = time.time()
        
        while True:
            try:
                try:
                    task = self._update_queue.get(timeout=1.0)
                    if task is None:
                        break
                    pending_updates.append(task)
                    self._update_queue.task_done()
                except queue.Empty:
                    pass
                
                if pending_updates and (len(pending_updates) >= 10 or time.time() - last_flush > 1.0):
                    self._flush_updates(pending_updates)
                    pending_updates = []
                    last_flush = time.time()
                    
            except Exception:
                pass
    
    def _flush_updates(self, updates):
        """批量执行更新"""
        for memory_id, collection in updates:
            try:
                result = collection.get(ids=[memory_id], include=["metadatas"])
                if result['metadatas']:
                    meta = result['metadatas'][0]
                    meta['access_count'] = meta.get('access_count', 0) + 1
                    meta['last_access'] = time.time()
                    collection.update(ids=[memory_id], metadatas=[meta])
            except Exception:
                pass
    
    def _is_review_question(self, text: str) -> bool:
        """
        检测是否为回顾性提问，如“你还记得我喜欢…吗”“我之前说过…”等
        """
        review_patterns = [
            '你还记得', '还记得我', '我之前说过', '我以前说过', '我刚才说', '我刚刚说',
            '我曾经说', '我刚才提到', '我刚刚提到', '我之前提到', '我以前提到',
            '你记得', '记得我', '你能回忆', '你能想起', '你能记得', '你能告诉我我',
            '我问过', '我说过', '我提过', '我提到过', '我讲过', '我讲到过',
            '你知道我', '你知道我喜欢', '你知道我讨厌', '你知道我最喜欢', '你知道我最讨厌',
            '你能猜', '你猜我', '你能想到', '你能想到我', '你能想到我喜欢', '你能想到我讨厌',
            '你能想到我最喜欢', '你能想到我最讨厌',
        ]
        # 疑问句标记
        question_marks = ['吗', '?', '？']
        if any(p in text for p in review_patterns) and any(q in text for q in question_marks):
            return True
        # 也允许“你还记得我喜欢吃什么”这类无问号但明显回顾性提问
        if any(p in text for p in review_patterns):
            return True
        return False

    def store_memory(self, conversation: str, current_emotion: str) -> str:
        """异步存储记忆（非阻塞）"""
        if not self.enabled:
            return current_emotion

        clean_conv = TextAnalyzer.clean_text(conversation)
        if len(clean_conv) < 5:
            return current_emotion

        # 回顾性提问不存储为记忆
        if self._is_review_question(clean_conv):
            logger.debug(f"[过滤] 回顾性提问未存储: {clean_conv}")
            return current_emotion

        entities = TextAnalyzer.extract_entities(clean_conv)
        emotion_type, emotion_intensity = TextAnalyzer.analyze_emotion(clean_conv)
        importance = TextAnalyzer.calculate_importance(clean_conv, entities, emotion_type, emotion_intensity)

        new_emotion = emotion_type if emotion_type != 'neutral' else current_emotion

        self._store_queue.put((clean_conv, entities, emotion_type, emotion_intensity, importance))
        return new_emotion
    
    def _do_store_memory(self, clean_conv, entities, emotion_type, emotion_intensity, importance):
        """实际存储操作（后台线程）"""
        memory_id = str(uuid.uuid4())
        user_input = extract_user_input(clean_conv)
        has_preference = ConflictDetector.detect_preference_conflict(user_input)
        preference_category = ConflictDetector.get_preference_category(user_input) if has_preference else None
        preference_polarity = None
        if has_preference:
            if any(p in user_input for p in PREFERENCE_PATTERNS['negative']):
                preference_polarity = 'negative'
            elif any(p in user_input for p in PREFERENCE_PATTERNS['positive']):
                preference_polarity = 'positive'

        metadata = {
            "timestamp": time.time(),
            "access_count": 0,
            "last_access": time.time(),
            "importance": importance,
            "emotion_type": emotion_type,
            "emotion_intensity": emotion_intensity,
            "entities": json.dumps(list(entities.keys())) if entities else "[]",
            "consolidated": False,
            "preference": bool(has_preference),
            "preference_category": preference_category or "",
            "preference_polarity": preference_polarity or "",
            "preference_entities": json.dumps(list(TextAnalyzer.extract_noun_entities(user_input))) if has_preference else "[]"
        }
        
        try:
            # 智能冲突检测与覆盖
            if self._conflict_resolver:
                self._conflict_resolver.smart_conflict_override(clean_conv, entities)
            
            # 根据重要性和情感存储到不同集合
            if emotion_intensity >= 2 or emotion_type == 'important':
                self.emotional.add(documents=[clean_conv], metadatas=[metadata], ids=[memory_id])
                logger.info(f"[存储] 情感记忆 | {clean_conv[:50]}... | 情感={emotion_type} 强度={emotion_intensity}")
            elif importance >= 0.35:
                metadata['consolidated'] = True
                self.long_term.add(documents=[clean_conv], metadatas=[metadata], ids=[memory_id])
                logger.info(f"[存储] 长期记忆 | {clean_conv[:50]}... | 重要度={importance:.2f}")
            else:
                self.long_term.add(documents=[clean_conv], metadatas=[metadata], ids=[memory_id])
                logger.debug(f"[存储] 工作记忆 | {clean_conv[:50]}... | 重要度={importance:.2f}")
                
        except Exception as e:
            logger.error(f"[存储失败] {clean_conv[:30]}... | 错误: {e}")
    
    def get_collections(self):
        """获取所有集合"""
        return self._collections
    
    def get_executor(self):
        """获取线程池"""
        return self._executor
    
    def get_update_queue(self):
        """获取更新队列"""
        return self._update_queue
    
    def cleanup_old_memories(self):
        """清理旧记忆"""
        if not self.enabled:
            return
        
        total_deleted = 0
        for collection, name in [(self.working, "工作记忆"), (self.long_term, "长期记忆")]:
            try:
                results = collection.get(include=["metadatas"])
                to_delete = [
                    doc_id for doc_id, meta in zip(results.get('ids', []), results.get('metadatas', []))
                    if meta and TextAnalyzer.calculate_memory_strength(meta) < 0.1 and meta.get('importance', 0.5) < 0.5
                ]
                if to_delete:
                    collection.delete(ids=to_delete)
                    total_deleted += len(to_delete)
                    logger.info(f"[清理] [{name}] 删除 {len(to_delete)} 条低强度记忆")
            except Exception as e:
                logger.error(f"[清理失败] [{name}] {e}")
        
        if total_deleted > 0:
            logger.info(f"[清理完成] 共删除 {total_deleted} 条记忆")

        # 全量语义矛盾检测与覆盖
        self.resolve_all_contradictions()
    
    def get_stats(self):
        """获取存储统计信息"""
        return {
            'working_memory': self.working.count() if self.working else 0,
            'long_term': self.long_term.count() if self.long_term else 0,
            'emotional': self.emotional.count() if self.emotional else 0,
            'pending_stores': self._store_queue.qsize(),
            'pending_updates': self._update_queue.qsize(),
        }

    def resolve_all_contradictions(self):
        """对所有记忆进行句意理解并清理矛盾对"""
        if not self.enabled or not self._conflict_resolver:
            return
        self._conflict_resolver.resolve_all_semantic_conflicts()
    
    def force_update_memory(self, old_info: str, new_info: str) -> bool:
        """强制更新记忆"""
        if not self.enabled:
            return False
        
        logger.info(f"[强制更新] 旧: {old_info} -> 新: {new_info}")
        
        deleted_count = 0
        for collection, layer_name in self._collections:
            try:
                results = collection.query(
                    query_texts=[old_info],
                    n_results=10,
                    include=["documents", "distances"]
                )
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]
                
                to_delete = [
                    doc_id for doc, dist, doc_id in zip(docs, distances, ids)
                    if dist < 0.8
                ]
                if to_delete:
                    collection.delete(ids=to_delete)
                    deleted_count += len(to_delete)
                    logger.info(f"[强制更新] 从[{layer_name}]删除 {len(to_delete)} 条")
                    print(f"   ├─ 从[{layer_name}]删除 {len(to_delete)} 条")
            except Exception as e:
                logger.error(f"[强制更新失败] [{layer_name}] {e}")
        
        # 存储新信息
        self.store_memory(f"用户更正: {new_info}", 'neutral')
        logger.info(f"[强制更新] 新记忆已存储")
        print(f"   └─ 新记忆已存储")
        
        return deleted_count > 0
    
    def clear_about(self, keyword: str) -> int:
        """清除关于某个关键词的所有记忆"""
        if not self.enabled:
            return 0
        
        logger.info(f"[清除记忆] 关键词: {keyword}")
        print(f"\n[🗑️ 清除记忆] 关键词: {keyword}")
        
        deleted_count = 0
        for collection, layer_name in self._collections:
            try:
                results = collection.query(
                    query_texts=[keyword],
                    n_results=20,
                    include=["documents", "distances"]
                )
                ids = results.get('ids', [[]])[0]
                distances = results.get('distances', [[]])[0]
                
                to_delete = [doc_id for doc_id, dist in zip(ids, distances) if dist < 0.7]
                if to_delete:
                    collection.delete(ids=to_delete)
                    deleted_count += len(to_delete)
                    logger.info(f"[清除记忆] 从[{layer_name}]删除 {len(to_delete)} 条")
                    print(f"   ├─ 从[{layer_name}]删除 {len(to_delete)} 条")
            except Exception as e:
                logger.error(f"[清除失败] [{layer_name}] {e}")
        
        logger.info(f"[清除记忆] 共删除 {deleted_count} 条")
        print(f"   └─ 共删除 {deleted_count} 条记忆")
        return deleted_count
    
    def close(self):
        """关闭存储系统"""
        logger.info("[关闭] 正在保存未完成的记忆...")
        print(" [记忆系统] 正在保存未完成的记忆...")
        
        self._store_queue.join()
        self._store_queue.put(None)
        self._update_queue.join()
        self._update_queue.put(None)
        self._executor.shutdown(wait=True)
        
        logger.info("[关闭] 所有记忆已保存完毕")
        logger.info(f"[关闭] 日志文件位置: {get_log_path()}")
        print(" [记忆系统] 所有记忆已保存完毕")
        print(f" [记忆系统] 日志文件: {get_log_path()}")
