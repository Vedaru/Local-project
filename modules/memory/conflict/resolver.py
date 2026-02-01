"""
冲突解决器 - Step 2 & 4: 检索与覆盖
"""
import json
from typing import List, Dict, Set, Tuple

from ..analyzers import TextAnalyzer
from ..logger import get_logger
from .constants import ENTITY_CONFLICT_THRESHOLD, SAME_CATEGORY_THRESHOLD
from .models import ConflictCandidate
from .locator import EntityLocator
from .detector import ConflictDetector
from .utils import extract_user_input

logger = get_logger()


class ConflictResolver:
    """
    冲突解决器 - 负责检索、判定与覆盖
    
    实现记忆覆盖四步流程：
    1. 定位 (由 EntityLocator 完成)
    2. 检索 - 基于实体和语义检索相关旧记忆
    3. 判定 - 调用 ConflictDetector 判断冲突
    4. 覆盖 - 物理删除旧记忆（新记忆由调用方插入）
    """
    
    def __init__(self, collections: list):
        """
        Args:
            collections: [(collection, layer_name), ...]
        """
        self.collections = collections
        self.logger = logger
    
    # ==================== Step 2: 检索 ====================
    def _query_by_entity(self, entity: str, n_results: int = 5) -> List[ConflictCandidate]:
        """基于实体关键词检索相关记忆"""
        candidates = []
        
        for collection, layer_name in self.collections:
            try:
                results = collection.query(
                    query_texts=[entity],
                    n_results=n_results,
                    include=["documents", "distances", "metadatas"]
                )
                
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]
                metas = results.get('metadatas', [[]])[0]
                
                for doc, dist, doc_id, meta in zip(docs, distances, ids, metas):
                    candidates.append(ConflictCandidate(
                        doc_id=doc_id,
                        document=doc,
                        distance=dist,
                        metadata=meta or {},
                        collection=collection,
                        layer_name=layer_name
                    ))
            except Exception as e:
                self.logger.error(f"[检索失败] [{layer_name}] entity={entity} | {e}")
        
        return candidates
    
    def _query_by_content(self, content: str, n_results: int = 5) -> List[ConflictCandidate]:
        """基于完整内容进行语义检索"""
        candidates = []
        
        for collection, layer_name in self.collections:
            try:
                results = collection.query(
                    query_texts=[content],
                    n_results=n_results,
                    include=["documents", "distances", "metadatas"]
                )
                
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]
                metas = results.get('metadatas', [[]])[0]
                
                for doc, dist, doc_id, meta in zip(docs, distances, ids, metas):
                    candidates.append(ConflictCandidate(
                        doc_id=doc_id,
                        document=doc,
                        distance=dist,
                        metadata=meta or {},
                        collection=collection,
                        layer_name=layer_name
                    ))
            except Exception as e:
                self.logger.error(f"[检索失败] [{layer_name}] | {e}")
        
        return candidates
    
    # ==================== Step 4: 删除 ====================
    def _execute_delete(self, candidates: List[ConflictCandidate]) -> int:
        """物理删除冲突记忆"""
        deleted_count = 0
        
        for candidate in candidates:
            try:
                candidate.collection.delete(ids=[candidate.doc_id])
                self.logger.info(
                    f"[冲突覆盖] 删除[{candidate.layer_name}] | "
                    f"原因={candidate.conflict_reason} | {candidate.document[:40]}..."
                )
                deleted_count += 1
            except Exception as e:
                self.logger.error(f"[删除失败] [{candidate.layer_name}] | {e}")
        
        return deleted_count
    
    # ==================== 主入口 ====================
    def smart_conflict_override(self, new_content: str, entities: dict) -> int:
        """
        智能冲突检测与覆盖（四步流程）
        
        Args:
            new_content: 新对话内容
            entities: 已提取的实体字典 {实体: 权重}
            
        Returns:
            删除的记忆数量
        """
        # Step 1: 定位
        primary_entities = EntityLocator.get_primary_entities(new_content, top_n=3)
        new_entities_set = set(entities.keys()) if entities else set()
        
        self.logger.debug(f"[定位] 核心实体: {primary_entities}")
        
        has_update_intent = ConflictDetector.has_update_intent(new_content)
        has_preference = ConflictDetector.detect_preference_conflict(new_content)
        
        # Step 2: 检索
        all_candidates: Dict[str, ConflictCandidate] = {}
        
        for entity in primary_entities:
            for candidate in self._query_by_entity(entity, n_results=5):
                if candidate.doc_id not in all_candidates:
                    all_candidates[candidate.doc_id] = candidate
        
        for candidate in self._query_by_content(new_content, n_results=5):
            if candidate.doc_id not in all_candidates:
                all_candidates[candidate.doc_id] = candidate
        
        self.logger.debug(f"[检索] 共找到 {len(all_candidates)} 条候选记忆")
        
        # Step 3: 判定
        to_delete: List[ConflictCandidate] = []
        
        for doc_id, candidate in all_candidates.items():
            doc = candidate.document
            dist = candidate.distance
            meta = candidate.metadata
            
            if doc.strip() == new_content.strip():
                continue
            
            try:
                old_entities = set(json.loads(meta.get('entities', '[]')))
            except Exception:
                old_entities = TextAnalyzer.extract_noun_entities(extract_user_input(doc))
            
            conflict_reason = ConflictDetector.judge_conflict(
                new_content=new_content,
                new_entities=new_entities_set,
                old_doc=doc,
                old_entities=old_entities,
                distance=dist,
                has_update_intent=has_update_intent,
                has_preference=has_preference
            )
            
            if conflict_reason:
                candidate.conflict_reason = conflict_reason
                to_delete.append(candidate)
        
        self.logger.debug(f"[判定] {len(to_delete)} 条记忆存在冲突")
        
        # Step 4: 覆盖
        return self._execute_delete(to_delete)

    def resolve_all_semantic_conflicts(self, max_neighbors: int = 5, similarity_threshold: float = 0.7) -> int:
        """全量语义冲突检测与清理"""
        def get_entities(text: str, meta: dict) -> Set[str]:
            try:
                meta_entities = set(json.loads(meta.get('entities', '[]'))) if meta else set()
            except Exception:
                meta_entities = set()
            if meta_entities:
                return meta_entities
            return TextAnalyzer.extract_noun_entities(extract_user_input(text))

        to_delete: Dict[str, Tuple] = {}

        for collection, layer_name in self.collections:
            try:
                results = collection.get(include=["documents", "metadatas", "ids"])
                docs = results.get('documents', [])
                metas = results.get('metadatas', [])
                ids = results.get('ids', [])

                for doc, meta, doc_id in zip(docs, metas, ids):
                    if doc_id in to_delete:
                        continue

                    for other_collection, other_layer in self.collections:
                        try:
                            neighbors = other_collection.query(
                                query_texts=[doc],
                                n_results=max_neighbors,
                                include=["documents", "distances", "metadatas", "ids"]
                            )
                            n_docs = neighbors.get('documents', [[]])[0]
                            n_distances = neighbors.get('distances', [[]])[0]
                            n_metas = neighbors.get('metadatas', [[]])[0]
                            n_ids = neighbors.get('ids', [[]])[0]

                            for n_doc, n_dist, n_meta, n_id in zip(n_docs, n_distances, n_metas, n_ids):
                                if n_id == doc_id or n_id in to_delete:
                                    continue
                                if n_dist > similarity_threshold:
                                    continue

                                new_ts = (meta or {}).get('timestamp', 0)
                                old_ts = (n_meta or {}).get('timestamp', 0)

                                if new_ts >= old_ts:
                                    new_text, old_text = doc, n_doc
                                    new_meta, old_meta = meta, n_meta
                                    old_id, old_layer, old_collection = n_id, other_layer, other_collection
                                else:
                                    new_text, old_text = n_doc, doc
                                    new_meta, old_meta = n_meta, meta
                                    old_id, old_layer, old_collection = doc_id, layer_name, collection

                                new_entities = get_entities(new_text, new_meta)
                                old_entities = get_entities(old_text, old_meta)
                                has_update_intent = ConflictDetector.has_update_intent(extract_user_input(new_text))
                                has_preference = ConflictDetector.detect_preference_conflict(extract_user_input(new_text))

                                conflict_reason = ConflictDetector.judge_conflict(
                                    new_content=new_text,
                                    new_entities=new_entities,
                                    old_doc=old_text,
                                    old_entities=old_entities,
                                    distance=n_dist,
                                    has_update_intent=has_update_intent,
                                    has_preference=has_preference
                                )

                                if conflict_reason:
                                    to_delete[old_id] = (old_collection, old_layer, old_text, conflict_reason)
                        except Exception:
                            pass
            except Exception:
                pass

        deleted_count = 0
        for old_id, (old_collection, old_layer, old_text, reason) in to_delete.items():
            try:
                old_collection.delete(ids=[old_id])
                self.logger.info(f"[全量矛盾清理] 删除[{old_layer}] | 原因={reason} | {old_text[:40]}...")
                deleted_count += 1
            except Exception as e:
                self.logger.error(f"[全量矛盾清理失败] [{old_layer}] | {e}")

        return deleted_count
    
    def quick_conflict_check(self, new_content: str, entity: str, threshold: float = None) -> int:
        """快速冲突检测 - 基于单个实体"""
        if threshold is None:
            threshold = ENTITY_CONFLICT_THRESHOLD
            
        deleted_count = 0
        
        for collection, layer_name in self.collections:
            try:
                results = collection.query(
                    query_texts=[entity],
                    n_results=5,
                    include=["documents", "distances", "metadatas"]
                )
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]
                
                to_delete = [
                    doc_id for doc, dist, doc_id in zip(docs, distances, ids)
                    if dist < threshold and doc.strip() != new_content.strip()
                ]
                
                if to_delete:
                    collection.delete(ids=to_delete)
                    deleted_count += len(to_delete)
                    self.logger.info(f"[快速冲突检测] 删除[{layer_name}] {len(to_delete)} 条 | entity={entity}")
            except Exception as e:
                self.logger.error(f"[快速冲突检测失败] [{layer_name}] | {e}")
        
        return deleted_count
    
    def override_memory(self, new_content: str, target_entity: str) -> int:
        """显式覆盖记忆 - 删除关于特定实体的所有旧记忆"""
        self.logger.info(f"[显式覆盖] entity={target_entity} | 新内容: {new_content[:50]}...")
        
        candidates = self._query_by_entity(target_entity, n_results=10)
        
        to_delete = []
        for candidate in candidates:
            if candidate.document.strip() == new_content.strip():
                continue
            if candidate.distance < SAME_CATEGORY_THRESHOLD:
                candidate.conflict_reason = "显式覆盖"
                to_delete.append(candidate)
        
        return self._execute_delete(to_delete)
