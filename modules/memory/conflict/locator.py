"""
实体定位器 - Step 1: 定位
"""
from typing import List, Optional

from ..config import PREFERENCE_CATEGORIES
from ..analyzers import TextAnalyzer
from .models import LocatedEntity
from .utils import extract_user_input


class EntityLocator:
    """
    实体定位器 - 负责从文本中提取核心实体关键词
    
    这是记忆覆盖的第一步：找到"关于谁"的记忆
    例："我现在不喜欢吃苹果了" -> 提取 "苹果"
    """
    
    @staticmethod
    def locate(text: str) -> List[LocatedEntity]:
        """
        从文本中定位核心实体
        
        Args:
            text: 输入文本
            
        Returns:
            实体列表，按权重降序排列
        """
        user_input = extract_user_input(text)
        entities = TextAnalyzer.extract_entities(user_input)
        
        located = []
        for entity, weight in entities.items():
            category = EntityLocator._get_entity_category(entity, user_input)
            located.append(LocatedEntity(
                entity=entity,
                weight=weight,
                category=category
            ))
        
        # 按权重降序排列
        located.sort(key=lambda x: x.weight, reverse=True)
        return located
    
    @staticmethod
    def _get_entity_category(entity: str, context: str) -> Optional[str]:
        """根据实体和上下文判断偏好类别"""
        for category, keywords in PREFERENCE_CATEGORIES.items():
            if any(kw in context for kw in keywords):
                return category
            # 实体本身可能就是类别关键词
            if entity in keywords:
                return category
        return None
    
    @staticmethod
    def get_primary_entities(text: str, top_n: int = 3) -> List[str]:
        """
        获取最重要的 N 个实体词（用于检索）
        
        Args:
            text: 输入文本
            top_n: 返回前 N 个实体
            
        Returns:
            实体词列表
        """
        located = EntityLocator.locate(text)
        return [e.entity for e in located[:top_n]]
