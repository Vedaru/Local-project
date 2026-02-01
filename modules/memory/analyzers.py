"""
文本分析器 - 实体提取、情感分析、重要性计算
"""
import math
import time
import jieba
import jieba.posseg as pseg

from .config import (
    ENTITY_WEIGHTS, ENTITY_FLAGS, 
    EMOTION_KEYWORDS, ALL_EMOTION_WORDS,
    CLEAN_PATTERN, SPACE_PATTERN,
    FORGETTING_RATE
)

# 预加载jieba词典（避免首次调用延迟）
jieba.initialize()


class TextAnalyzer:
    """文本分析器"""
    
    @staticmethod
    def extract_entities(text: str) -> dict:
        """
        快速实体提取
        返回: {实体词: 权重}
        """
        entities = {}
        for word, flag in pseg.cut(text):
            if flag in ENTITY_FLAGS and len(word) >= 2:
                entities[word] = max(entities.get(word, 0), ENTITY_WEIGHTS[flag])
        return entities

    @staticmethod
    def analyze_emotion(text: str) -> tuple:
        """
        快速情感分析
        返回: (情感类型, 强度)
        """
        # 先检查是否包含任何情感词
        if not any(c in text for word in ALL_EMOTION_WORDS for c in word[:1]):
            return 'neutral', 0
        
        scores = {k: sum(1 for kw in v if kw in text) for k, v in EMOTION_KEYWORDS.items()}
        max_emotion = max(scores, key=scores.get)
        intensity = scores[max_emotion]
        
        return (max_emotion, min(intensity, 5)) if intensity > 0 else ('neutral', 0)

    @staticmethod
    def calculate_importance(text: str, entities: dict, emotion_type: str, emotion_intensity: int) -> float:
        """计算文本重要性"""
        score = 0.3
        if entities:
            score += min(sum(entities.values()) / len(entities) * 0.1, 0.2)
        if emotion_type != 'neutral':
            score += emotion_intensity * 0.08
        if emotion_type == 'important':
            score += 0.2
        if 20 <= len(text) <= 100:
            score += 0.1
        return min(score, 1.0)

    @staticmethod
    def calculate_memory_strength(metadata: dict) -> float:
        """计算记忆强度（艾宾浩斯遗忘曲线）"""
        importance = metadata.get('importance', 0.5)
        access_count = metadata.get('access_count', 0)
        last_access = metadata.get('last_access', metadata.get('timestamp', time.time()))
        hours_since = (time.time() - last_access) / 3600
        
        base = importance * math.exp(-FORGETTING_RATE * hours_since / 24)
        boost = 1 + math.log(1 + access_count) * 0.3
        return min(base * boost, 1.0)

    @staticmethod
    def clean_text(text: str) -> str:
        """快速文本清洗"""
        text = CLEAN_PATTERN.sub('', text)
        return SPACE_PATTERN.sub(' ', text).strip()

    @staticmethod
    def extract_noun_entities(text: str) -> set:
        """提取名词实体（用于偏好冲突检测）"""
        return set(word for word, flag in pseg.cut(text) if flag.startswith('n') and len(word) >= 2)
