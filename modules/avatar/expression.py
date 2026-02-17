"""
表情管理模块 - 基于文本情感分析的表情控制

NOTE: Several methods and dataclasses in this module are part of the public
Avatar expression API and may be called dynamically by the Avatar manager or
external code. Keep public method signatures stable to preserve compatibility.
"""

from typing import Callable, Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .logger import log_info, log_debug


class Emotion(Enum):
    """情感类型枚举"""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THINKING = "thinking"
    SHY = "shy"
    CONFUSED = "confused"


@dataclass
class ExpressionConfig:
    """表情配置"""
    emotion: Emotion
    expression_index: int  # Live2D 模型的表情索引
    motion_group: Optional[str] = None  # 可选的配套动作组
    motion_index: Optional[int] = None  # 可选的配套动作索引
    priority: int = 1  # 优先级（用于冲突解决）


@dataclass
class EmotionKeywords:
    """情感关键词配置"""
    positive: List[str] = field(default_factory=lambda: [
        '开心', '高兴', '快乐', '好', '棒', '喜欢', '爱', '哈哈', '嘻嘻', '嘿嘿',
        '太好了', '真棒', '厉害', '赞', '不错', '可以', '行', '好的', '好呀',
        '哇', '耶', '欢迎', '谢谢', '感谢', '开玩笑', '有趣', '好玩', '笑',
        '😊', '😄', '😃', '🎉', '👍', '❤️', '💕', '🥰', '😘',
    ])
    negative: List[str] = field(default_factory=lambda: [
        '难过', '伤心', '悲伤', '哭', '痛', '累', '烦', '郁闷', '无聊',
        '讨厌', '不喜欢', '不想', '不要', '算了', '唉', '呜呜', '呜',
        '对不起', '抱歉', '遗憾', '可惜', '失望', '沮丧',
        '😢', '😭', '😔', '😞', '💔',
    ])
    angry: List[str] = field(default_factory=lambda: [
        '生气', '愤怒', '烦死', '讨厌', '滚', '闭嘴', '可恶', '混蛋',
        '什么鬼', '搞什么', '气死', '受不了', '不爽',
        '😠', '😡', '🤬', '💢',
    ])
    surprised: List[str] = field(default_factory=lambda: [
        '惊讶', '震惊', '天哪', '我的天', '什么', '真的吗', '不会吧',
        '居然', '竟然', '没想到', '想不到', '意外', '突然',
        '😮', '😲', '😱', '🤯', '❗', '❓',
    ])
    shy: List[str] = field(default_factory=lambda: [
        '害羞', '不好意思', '羞', '脸红', '尴尬', '那个', '嗯...',
        '人家', '讨厌啦', '别这样', '哎呀',
        '😳', '🙈', '😅',
    ])
    confused: List[str] = field(default_factory=lambda: [
        '困惑', '不懂', '不明白', '什么意思', '为什么', '怎么',
        '奇怪', '疑惑', '迷茫', '不知道', '不确定',
        '🤔', '❓', '😕',
    ])


class EmotionAnalyzer:
    """情感分析器 - 分析文本中的情感"""

    def __init__(self, keywords: Optional[EmotionKeywords] = None):
        self.keywords = keywords or EmotionKeywords()

        # 构建情感-关键词映射
        self._emotion_keywords: Dict[Emotion, List[str]] = {
            Emotion.HAPPY: self.keywords.positive,
            Emotion.SAD: self.keywords.negative,
            Emotion.ANGRY: self.keywords.angry,
            Emotion.SURPRISED: self.keywords.surprised,
            Emotion.SHY: self.keywords.shy,
            Emotion.CONFUSED: self.keywords.confused,
        }

        # 标点符号情感映射
        self._punctuation_emotions = {
            '！': (Emotion.HAPPY, 0.3),
            '!': (Emotion.HAPPY, 0.3),
            '？': (Emotion.CONFUSED, 0.2),
            '?': (Emotion.CONFUSED, 0.2),
            '...': (Emotion.THINKING, 0.2),
            '……': (Emotion.THINKING, 0.2),
            '~': (Emotion.HAPPY, 0.2),
            '～': (Emotion.HAPPY, 0.2),
        }

    def analyze(self, text: str) -> Tuple[Emotion, float]:
        """
        分析文本的情感
        
        Args:
            text: 要分析的文本
        
        Returns:
            (情感类型, 置信度) 的元组
        """
        if not text:
            return Emotion.NEUTRAL, 0.0

        text_lower = text.lower()
        scores: Dict[Emotion, float] = {e: 0.0 for e in Emotion}

        # 关键词匹配
        for emotion, keywords in self._emotion_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    # 根据关键词长度给予不同权重
                    weight = 0.5 + len(keyword) * 0.1
                    scores[emotion] += weight

        # 标点符号分析
        for punct, (emotion, weight) in self._punctuation_emotions.items():
            count = text.count(punct)
            scores[emotion] += count * weight

        # 感叹号多表示强烈情感
        exclaim_count = text.count('！') + text.count('!')
        if exclaim_count >= 2:
            # 增强当前最高情感
            max_emotion = max(scores, key=scores.get)
            scores[max_emotion] += exclaim_count * 0.2

        # 找出最高分的情感
        max_emotion = max(scores, key=scores.get)
        max_score = scores[max_emotion]

        # 如果分数太低，返回中性
        if max_score < 0.3:
            return Emotion.NEUTRAL, 0.0

        # 计算置信度（归一化）
        confidence = min(1.0, max_score / 3.0)

        log_debug(f"Emotion analysis: {max_emotion.value} (confidence: {confidence:.2f})")
        return max_emotion, confidence

    def add_keywords(self, emotion: Emotion, keywords: List[str]):
        """添加自定义关键词"""
        if emotion in self._emotion_keywords:
            self._emotion_keywords[emotion].extend(keywords)


class ExpressionManager:
    """表情管理器 - 管理和控制 Live2D 模型的表情"""

    # 默认表情配置
    DEFAULT_EXPRESSIONS: Dict[Emotion, ExpressionConfig] = {
        Emotion.NEUTRAL: ExpressionConfig(Emotion.NEUTRAL, 0, None, None, 1),
        Emotion.HAPPY: ExpressionConfig(Emotion.HAPPY, 2, "TapBody", None, 2),
        Emotion.SAD: ExpressionConfig(Emotion.SAD, 3, None, None, 2),
        Emotion.ANGRY: ExpressionConfig(Emotion.ANGRY, 4, None, None, 3),
        Emotion.SURPRISED: ExpressionConfig(Emotion.SURPRISED, 5, None, None, 3),
        Emotion.THINKING: ExpressionConfig(Emotion.THINKING, 1, None, None, 1),
        Emotion.SHY: ExpressionConfig(Emotion.SHY, 6, None, None, 2),
        Emotion.CONFUSED: ExpressionConfig(Emotion.CONFUSED, 7, None, None, 1),
    }

    def __init__(
        self,
        expression_callback: Callable[[int], None],
        motion_callback: Optional[Callable[[str, int], None]] = None,
        expression_config: Optional[Dict[Emotion, ExpressionConfig]] = None
    ):
        """
        Args:
            expression_callback: 表情切换回调，接收表情索引
            motion_callback: 动作播放回调，接收动作组和索引
            expression_config: 自定义表情配置
        """
        self._expression_callback = expression_callback
        self._motion_callback = motion_callback
        self._expressions = expression_config or self.DEFAULT_EXPRESSIONS.copy()
        self._analyzer = EmotionAnalyzer()
        self._current_emotion = Emotion.NEUTRAL

        log_info("ExpressionManager initialized")

    def set_expression_config(self, emotion: Emotion, config: ExpressionConfig):
        """设置表情配置"""
        self._expressions[emotion] = config

    def get_expression_config(self, emotion: Emotion) -> Optional[ExpressionConfig]:
        """获取表情配置"""
        return self._expressions.get(emotion)

    def set_emotion(self, emotion: Emotion, play_motion: bool = True):
        """
        设置表情
        
        Args:
            emotion: 情感类型
            play_motion: 是否播放配套动作
        """
        config = self._expressions.get(emotion)
        if not config:
            log_debug(f"No config for emotion: {emotion.value}, using neutral")
            config = self._expressions.get(Emotion.NEUTRAL)

        if config:
            # 切换表情
            self._expression_callback(config.expression_index)
            self._current_emotion = emotion

            # 播放配套动作
            if play_motion and self._motion_callback and config.motion_group:
                self._motion_callback(
                    config.motion_group,
                    config.motion_index if config.motion_index is not None else 0
                )

            log_debug(f"Expression set: {emotion.value} (index: {config.expression_index})")

    def set_expression_from_text(self, text: str, play_motion: bool = True) -> Emotion:
        """
        根据文本内容自动设置表情
        
        Args:
            text: 文本内容
            play_motion: 是否播放配套动作
        
        Returns:
            检测到的情感
        """
        emotion, confidence = self._analyzer.analyze(text)

        # 只有置信度足够高才切换表情
        if confidence >= 0.3:
            self.set_emotion(emotion, play_motion=play_motion)
        else:
            # 保持当前表情或切换到中性
            if self._current_emotion == Emotion.THINKING:
                self.set_emotion(Emotion.NEUTRAL, play_motion=False)

        return emotion

    def set_thinking(self):
        """设置思考表情"""
        self.set_emotion(Emotion.THINKING, play_motion=False)

    def reset(self):
        """重置为中性表情"""
        self.set_emotion(Emotion.NEUTRAL, play_motion=False)

    @property
    def current_emotion(self) -> Emotion:
        """当前情感"""
        return self._current_emotion

    def add_keywords(self, emotion: Emotion, keywords: List[str]):
        """添加情感关键词"""
        self._analyzer.add_keywords(emotion, keywords)
