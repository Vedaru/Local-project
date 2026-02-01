"""
冲突判定器 - Step 3: 判定
"""
from typing import Set, Optional

from ..config import (
    UPDATE_INDICATORS, 
    PREFERENCE_PATTERNS, 
    PREFERENCE_PAIRS,
    PREFERENCE_CATEGORIES
)
from ..analyzers import TextAnalyzer
from ..logger import get_logger
from .constants import (
    EXACT_DUPLICATE_THRESHOLD,
    ENTITY_CONFLICT_THRESHOLD,
    PREFERENCE_CONFLICT_THRESHOLD,
    SAME_CATEGORY_THRESHOLD
)
from .utils import extract_user_input, is_question

logger = get_logger()


class ConflictDetector:
    """
    冲突判定器 - 判断新旧记忆是否存在冲突
    
    这是记忆覆盖的第三步：判定哪条旧记忆"该消失"
    
    判定逻辑：
    1. 极高相似度（distance < 0.15）-> 重复记忆
    2. 更新意图 + 共同实体 + 较高相似度 -> 信息更正
    3. 同一对象的矛盾偏好（喜欢 vs 不喜欢）-> 偏好冲突
    4. 同类别偏好更新（喜欢苹果 -> 喜欢香蕉）-> 同类偏好覆盖
    """
    
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
        if is_question(text):
            return False
        
        if '我' not in text:
            return False
        
        for patterns in PREFERENCE_PATTERNS.values():
            if any(p in text for p in patterns):
                return True
        return False
    
    @staticmethod
    def get_preference_category(text: str) -> Optional[str]:
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
        """
        new_user_input = extract_user_input(new_text)
        old_user_input = extract_user_input(old_text)
        
        # 排除疑问句
        if is_question(new_user_input) or is_question(old_user_input):
            return False
        
        # 都必须包含偏好表达
        if not ConflictDetector.detect_preference_conflict(new_user_input):
            return False
        if not ConflictDetector.detect_preference_conflict(old_user_input):
            return False
        
        # 检查是否同一偏好类别
        new_category = ConflictDetector.get_preference_category(new_user_input)
        old_category = ConflictDetector.get_preference_category(old_user_input)
        
        if new_category and old_category and new_category == old_category:
            logger.info(f"[同类偏好检测] 类别={new_category} | 新: {new_user_input[:30]}... | 旧: {old_user_input[:30]}...")
            return True
        
        return False
    
    @staticmethod
    def is_preference_contradiction(new_text: str, old_text: str) -> bool:
        """
        检测两条记忆是否存在偏好矛盾
        例如："我喜欢吃苹果" vs "我不喜欢吃苹果"
        """
        new_user_input = extract_user_input(new_text)
        old_user_input = extract_user_input(old_text)
        
        # 排除疑问句
        if is_question(new_user_input) or is_question(old_user_input):
            return False
        
        # 必须都包含主语"我"
        if '我' not in new_user_input or '我' not in old_user_input:
            return False
        
        # 提取共同对象词
        new_words = TextAnalyzer.extract_noun_entities(new_user_input)
        old_words = TextAnalyzer.extract_noun_entities(old_user_input)
        common_objects = new_words & old_words
        
        if not common_objects:
            return False
        
        # 检查偏好矛盾
        for pos, neg in PREFERENCE_PAIRS:
            if neg in new_user_input and pos in old_user_input and neg not in old_user_input:
                logger.info(f"[偏好矛盾检测] 新:'{neg}' vs 旧:'{pos}' | 共同对象: {common_objects}")
                return True
            if pos in new_user_input and neg in old_user_input and neg not in new_user_input:
                logger.info(f"[偏好矛盾检测] 新:'{pos}' vs 旧:'{neg}' | 共同对象: {common_objects}")
                return True
        
        return False
    
    @staticmethod
    def judge_conflict(
        new_content: str,
        new_entities: Set[str],
        old_doc: str,
        old_entities: Set[str],
        distance: float,
        has_update_intent: bool,
        has_preference: bool
    ) -> Optional[str]:
        """
        综合判定是否存在冲突（核心判定方法）
        
        Args:
            new_content: 新记忆内容
            new_entities: 新记忆实体集合
            old_doc: 旧记忆内容
            old_entities: 旧记忆实体集合
            distance: 语义距离
            has_update_intent: 是否有更新意图
            has_preference: 是否包含偏好表达
            
        Returns:
            冲突原因（None 表示无冲突）
        """
        # 条件1：极高相似度（几乎完全重复）
        if distance < EXACT_DUPLICATE_THRESHOLD:
            return "重复"
        
        common_entities = new_entities & old_entities
        
        # 条件2：有更新意图 + 有共同核心实体 + 较高相似度
        if has_update_intent and common_entities and distance < ENTITY_CONFLICT_THRESHOLD:
            return "更新"
        
        # 条件3：偏好冲突检测
        if has_preference and distance < PREFERENCE_CONFLICT_THRESHOLD:
            if ConflictDetector.is_preference_contradiction(new_content, old_doc):
                return "偏好矛盾"
        
        # 条件4：同类偏好更新检测（不依赖距离，避免漏判）
        if has_preference:
            if ConflictDetector.is_same_category_preference(new_content, old_doc):
                return "同类偏好更新"
        
        return None
