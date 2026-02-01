"""
冲突检测与覆盖模块
处理记忆矛盾、偏好冲突等
"""
import json
from .config import (
    UPDATE_INDICATORS, 
    PREFERENCE_PATTERNS, 
    PREFERENCE_PAIRS,
    PREFERENCE_UPDATE_PATTERNS,
    PREFERENCE_CATEGORIES,
    SENTENCE_CONFLICT_THRESHOLD
)
from .logger import get_logger
from .analyzers import TextAnalyzer

logger = get_logger()


class ConflictDetector:
    """冲突检测器"""
    
    @staticmethod
    def has_update_intent(text: str) -> bool:
        """检测文本是否包含更新/更正意图"""
        return any(indicator in text for indicator in UPDATE_INDICATORS)
    
    @staticmethod
    def detect_preference_conflict(text: str) -> bool:
        """
        检测文本中是否包含偏好表达（喜欢/不喜欢类型）
        
        必须满足：
        1. 包含偏好词（喜欢/不喜欢等）
        2. 有明确主语（我）
        3. 不是疑问句
        """
        # 排除疑问句
        question_indicators = ['吗', '呢', '吧', '?', '？', '什么', '哪', '怎么', '为什么', '还记得']
        if any(ind in text for ind in question_indicators):
            return False
        
        # 必须包含主语"我"
        if '我' not in text:
            return False
        
        # 检查是否包含偏好词
        for patterns in PREFERENCE_PATTERNS.values():
            if any(p in text for p in patterns):
                return True
        return False
    
    @staticmethod
    def has_preference_update_intent(text: str) -> bool:
        """检测文本是否表示偏好更新（如"我现在喜欢吃X"）"""
        return any(pattern in text for pattern in PREFERENCE_UPDATE_PATTERNS)
    
    @staticmethod
    def get_preference_category(text: str) -> str:
        """获取文本涉及的偏好类别"""
        for category, keywords in PREFERENCE_CATEGORIES.items():
            if any(kw in text for kw in keywords):
                return category
        return None
    
    @staticmethod
    def is_same_category_preference(new_text: str, old_text: str) -> bool:
        """
        检测两条记忆是否属于同一类别的偏好
        例如："我喜欢吃香蕉" 和 "喜欢吃苹果" 都是食物偏好
        
        重要条件：
        1. 新文本必须是用户的偏好声明（以"用户:"开头且包含偏好词）
        2. 旧文本也必须是用户的偏好声明
        3. 两者必须属于同一偏好类别
        4. 排除询问句（如"你还记得我喜欢吃什么吗"）
        """
        # 提取用户的实际输入（去掉"用户: "和AI回复部分）
        def extract_user_input(text: str) -> str:
            if '用户:' in text:
                user_part = text.split('用户:')[1].split('AI:')[0].strip()
                return user_part
            return text
        
        new_user_input = extract_user_input(new_text)
        old_user_input = extract_user_input(old_text)
        
        # 检查1：排除疑问句（不应该被当作偏好声明）
        question_indicators = ['吗', '呢', '吧', '?', '？', '什么', '哪', '怎么', '为什么']
        if any(ind in new_user_input for ind in question_indicators):
            return False
        if any(ind in old_user_input for ind in question_indicators):
            return False
        
        # 检查2：新文本必须包含偏好表达
        has_new_preference = ConflictDetector.detect_preference_conflict(new_user_input)
        if not has_new_preference:
            return False
        
        # 检查3：旧文本必须包含偏好表达
        has_old_preference = ConflictDetector.detect_preference_conflict(old_user_input)
        if not has_old_preference:
            return False
        
        # 检查4：检查是否同一偏好类别
        new_category = ConflictDetector.get_preference_category(new_user_input)
        old_category = ConflictDetector.get_preference_category(old_user_input)
        
        # 同类别偏好：只保留最新的
        if new_category and old_category and new_category == old_category:
            logger.info(f"[同类偏好检测] 类别={new_category} | 新: {new_user_input[:30]}... | 旧: {old_user_input[:30]}...")
            return True
        
        return False
    
    @staticmethod
    def is_preference_contradiction(new_text: str, old_text: str) -> bool:
        """
        检测两条记忆是否存在偏好矛盾
        例如："我喜欢吃苹果" vs "我不喜欢吃苹果"
        
        只比较用户的实际输入，排除AI回答和疑问句
        """
        # 提取用户的实际输入（去掉"用户: "和AI回复部分）
        def extract_user_input(text: str) -> str:
            if '用户:' in text:
                user_part = text.split('用户:')[1].split('AI:')[0].strip()
                return user_part
            return text
        
        new_user_input = extract_user_input(new_text)
        old_user_input = extract_user_input(old_text)
        
        # 排除疑问句
        question_indicators = ['吗', '呢', '吧', '?', '？', '什么', '哪', '怎么', '为什么', '还记得']
        if any(ind in new_user_input for ind in question_indicators):
            return False
        if any(ind in old_user_input for ind in question_indicators):
            return False
        
        # 必须都包含主语"我"
        if '我' not in new_user_input or '我' not in old_user_input:
            return False
        
        # 提取两个文本中的关键对象词
        new_words = TextAnalyzer.extract_noun_entities(new_user_input)
        old_words = TextAnalyzer.extract_noun_entities(old_user_input)
        
        # 找到共同的对象词（例如"苹果"、"香蕉"等）
        common_objects = new_words & old_words
        
        if not common_objects:
            return False
        
        # 检查是否存在偏好矛盾
        for pos, neg in PREFERENCE_PAIRS:
            # 情况1：新文本是否定，旧文本是肯定
            if neg in new_user_input and pos in old_user_input and neg not in old_user_input:
                logger.info(f"[偏好矛盾检测] 新:'{neg}' vs 旧:'{pos}' | 共同对象: {common_objects}")
                return True
            # 情况2：新文本是肯定，旧文本是否定
            if pos in new_user_input and neg in old_user_input and neg not in new_user_input:
                logger.info(f"[偏好矛盾检测] 新:'{pos}' vs 旧:'{neg}' | 共同对象: {common_objects}")
                return True
        
        return False


class ConflictResolver:
    """冲突解决器"""
    
    def __init__(self, collections: list):
        """
        Args:
            collections: [(collection, layer_name), ...]
        """
        self.collections = collections
        self.logger = logger
    
    def smart_conflict_override(self, new_content: str, entities: dict):
        """
        智能冲突检测与覆盖
        在以下情况删除旧记忆：
        1. 完全相同的对话（去重）
        2. 用户明确表示更正 + 有共同核心实体
        3. 偏好冲突："喜欢X" vs "不喜欢X"
        4. 同类偏好更新："我喜欢吃香蕉" 覆盖 "喜欢吃苹果"（即使没有"现在"等更新词）
        """
        has_update_intent = ConflictDetector.has_update_intent(new_content)
        has_preference = ConflictDetector.detect_preference_conflict(new_content)
        
        new_entities_set = set(entities.keys()) if entities else set()
        to_delete_all = []
        
        for collection, layer_name in self.collections:
            try:
                results = collection.query(
                    query_texts=[new_content],
                    n_results=5,  # 增加检索数量以更好地检测同类偏好
                    include=["documents", "distances", "metadatas"]
                )
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]
                metas = results.get('metadatas', [[]])[0]
                
                for doc, dist, doc_id, meta in zip(docs, distances, ids, metas):
                    # 跳过完全相同的内容
                    if doc.strip() == new_content.strip():
                        continue
                    
                    old_entities = set(json.loads(meta.get('entities', '[]')))
                    common_entities = old_entities & new_entities_set
                    
                    # 条件1：极高相似度（几乎相同的对话）
                    if dist < 0.2:
                        to_delete_all.append((collection, doc_id, doc, layer_name, "重复"))
                        continue
                    
                    # 条件2：有更新意图 + 有共同核心实体 + 较高相似度
                    if has_update_intent and common_entities and dist < SENTENCE_CONFLICT_THRESHOLD:
                        to_delete_all.append((collection, doc_id, doc, layer_name, "更新"))
                        continue
                    
                    # 条件3：偏好冲突检测（同一对象的矛盾偏好）
                    if has_preference and dist < 0.5:
                        if ConflictDetector.is_preference_contradiction(new_content, doc):
                            to_delete_all.append((collection, doc_id, doc, layer_name, "偏好矛盾"))
                            continue
                    
                    # 条件4：同类偏好更新检测（如"喜欢吃香蕉"覆盖"喜欢吃苹果"）
                    # 放宽距离限制到0.7，以便更好地捕获同类偏好
                    if has_preference and dist < 0.7:
                        if ConflictDetector.is_same_category_preference(new_content, doc):
                            to_delete_all.append((collection, doc_id, doc, layer_name, "同类偏好更新"))
                            
            except Exception:
                pass
        
        # 执行删除
        if to_delete_all:
            for collection, doc_id, doc, layer_name, reason in to_delete_all:
                try:
                    collection.delete(ids=[doc_id])
                    self.logger.info(f"[冲突覆盖] 删除[{layer_name}] | 原因={reason} | {doc[:40]}...")
                except Exception as e:
                    self.logger.error(f"[删除失败] [{layer_name}] | {e}")
    
    def quick_conflict_check(self, new_content: str, entity: str, threshold: float):
        """快速冲突检测"""
        for collection, _ in self.collections:
            try:
                results = collection.query(
                    query_texts=[entity],
                    n_results=2,
                    include=["documents", "distances"]
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
            except Exception:
                pass
