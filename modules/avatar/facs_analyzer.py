"""
FACS (面部动作编码系统) 表情分析器

将文本情感分析转换为 FACS 动作单元 (Action Units, AUs)，
再将 AUs 映射到 Live2D 面部参数。

参考: Paul Ekman 的 FACS 系统
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FACSActionUnit(Enum):
    """FACS 动作单元定义"""

    # 眉毛区域
    AU1 = "AU1"  # 内眉上扬 (Inner Brow Raise)
    AU2 = "AU2"  # 外眉上扬 (Outer Brow Raise)
    AU4 = "AU4"  # 眉毛下压 (Brow Lowerer)

    # 眼睛区域
    AU5 = "AU5"  # 上眼睑上扬 (Upper Lid Raise)
    AU6 = "AU6"  # 脸颊上扬 (Cheek Raise)
    AU7 = "AU7"  # 眼睑紧缩 (Lid Tightener)
    AU43 = "AU43"  # 眼睛闭合 (Eye Closure)
    AU45 = "AU45"  # 眨眼 (Blink)

    # 鼻子区域
    AU9 = "AU9"  # 鼻皱 (Nose Wrinkler)

    # 嘴巴区域
    AU10 = "AU10"  # 上唇上扬 (Upper Lip Raiser)
    AU12 = "AU12"  # 嘴角上扬 (Lip Corner Puller) - 微笑
    AU13 = "AU13"  # 急速嘴角上扬 (Sharp Lip Puller)
    AU14 = "AU14"  # 酒窝 (Dimpler)
    AU15 = "AU15"  # 嘴角下拉 (Lip Corner Depressor)
    AU17 = "AU17"  # 下唇上推 (Lower Lip Raiser)
    AU20 = "AU20"  # 嘴唇伸展 (Lip Stretcher)
    AU23 = "AU23"  # 嘴唇收紧 (Lip Tightener)
    AU24 = "AU24"  # 嘴唇按压 (Lip Pressor)
    AU25 = "AU25"  # 嘴唇分开 (Lips Part)
    AU26 = "AU26"  # 下颌下拉 (Jaw Drop)
    AU27 = "AU27"  # 嘴巴张开 (Mouth Stretch)


@dataclass
class FACSState:
    """FACS 动作单元状态"""

    # 每个 AU 的强度 (0-5，FACS 标准强度)
    au_intensities: dict[FACSActionUnit, float] = field(default_factory=dict)

    def set_au(self, au: FACSActionUnit, intensity: float):
        """设置 AU 强度 (0-5)"""
        self.au_intensities[au] = max(0, min(5, intensity))

    def get_au(self, au: FACSActionUnit) -> float:
        """获取 AU 强度"""
        return self.au_intensities.get(au, 0)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {au.value: intensity for au, intensity in self.au_intensities.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "FACSState":
        """从字典创建"""
        state = cls()
        for au_str, intensity in data.items():
            try:
                au = FACSActionUnit(au_str)
                state.set_au(au, float(intensity))
            except (ValueError, TypeError):
                continue
        return state


@dataclass
class Live2DParams:
    """Live2D 面部参数"""

    brow_l_form: float = 0  # 左眉形状 (-1 到 1)
    brow_r_form: float = 0  # 右眉形状
    eye_l_open: float = 1  # 左眼开合 (0-1)
    eye_r_open: float = 1  # 右眼开合
    eye_l_smile: float = 0  # 左眼微笑 (0-1)
    eye_r_smile: float = 0  # 右眼微笑
    eye_ball_x: float = 0  # 眼球水平 (-1 到 1)
    eye_ball_y: float = 0  # 眼球垂直 (-1 到 1)
    cheek: float = 0  # 脸颊 (0-1)
    mouth_open: float = 0  # 嘴巴开合 (0-1)
    mouth_form: float = 0  # 嘴巴形状 (-1 到 1)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "browLForm": round(self.brow_l_form, 4),
            "browRForm": round(self.brow_r_form, 4),
            "eyeLOpen": round(self.eye_l_open, 4),
            "eyeROpen": round(self.eye_r_open, 4),
            "eyeLSmile": round(self.eye_l_smile, 4),
            "eyeRSmile": round(self.eye_r_smile, 4),
            "eyeBallX": round(self.eye_ball_x, 4),
            "eyeBallY": round(self.eye_ball_y, 4),
            "cheek": round(self.cheek, 4),
            "mouthOpen": round(self.mouth_open, 4),
            "mouthForm": round(self.mouth_form, 4),
        }


# ============================================================
# 情绪到 FACS AU 的映射
# ============================================================

EMOTION_AU_MAPPINGS = {
    "happy": {
        FACSActionUnit.AU1: 1.5,  # 内眉微扬（开心时眉毛自然上扬）
        FACSActionUnit.AU2: 1.5,  # 外眉微扬
        FACSActionUnit.AU6: 3.0,  # 脸颊上扬
        FACSActionUnit.AU12: 4.0,  # 嘴角上扬（微笑）
        FACSActionUnit.AU25: 1.0,  # 嘴唇分开
    },
    "sad": {
        FACSActionUnit.AU1: 3.0,  # 内眉上扬
        FACSActionUnit.AU4: 2.0,  # 眉毛下压
        FACSActionUnit.AU15: 3.0,  # 嘴角下拉
        FACSActionUnit.AU17: 2.0,  # 下唇上推
    },
    "angry": {
        FACSActionUnit.AU4: 4.0,  # 眉毛下压
        FACSActionUnit.AU5: 3.0,  # 上眼睑上扬
        FACSActionUnit.AU7: 3.0,  # 眼睑紧缩
        FACSActionUnit.AU23: 3.0,  # 嘴唇收紧
        FACSActionUnit.AU24: 2.0,  # 嘴唇按压
    },
    "surprised": {
        FACSActionUnit.AU1: 4.0,  # 内眉上扬
        FACSActionUnit.AU2: 4.0,  # 外眉上扬
        FACSActionUnit.AU5: 4.0,  # 上眼睑上扬
        FACSActionUnit.AU26: 4.0,  # 下颌下拉
    },
    "fear": {
        FACSActionUnit.AU1: 4.0,  # 内眉上扬
        FACSActionUnit.AU2: 3.0,  # 外眉上扬
        FACSActionUnit.AU4: 2.0,  # 眉毛下压
        FACSActionUnit.AU5: 4.0,  # 上眼睑上扬
        FACSActionUnit.AU20: 3.0,  # 嘴唇伸展
        FACSActionUnit.AU26: 3.0,  # 下颌下拉
    },
    "disgust": {
        FACSActionUnit.AU9: 4.0,  # 鼻皱
        FACSActionUnit.AU10: 3.0,  # 上唇上扬
        FACSActionUnit.AU17: 2.0,  # 下唇上推
    },
    "contempt": {
        FACSActionUnit.AU12: 2.0,  # 嘴角上扬（单侧）
        FACSActionUnit.AU14: 3.0,  # 酒窝（单侧）
    },
    "thinking": {
        FACSActionUnit.AU1: 1.0,  # 内眉微扬
        FACSActionUnit.AU4: 1.5,  # 眉毛微压
        FACSActionUnit.AU7: 1.0,  # 眼睑微缩
    },
    "shy": {
        FACSActionUnit.AU6: 2.0,  # 脸颊上扬
        FACSActionUnit.AU12: 1.5,  # 微笑
        FACSActionUnit.AU43: 2.0,  # 眼睛半闭
    },
    "neutral": {},  # 中性表情无特定 AU
}


# ============================================================
# FACS AU 到 Live2D 参数的映射
# ============================================================


def au_to_live2d(facs_state: FACSState) -> Live2DParams:
    """将 FACS AU 状态转换为 Live2D 面部参数"""
    params = Live2DParams()

    # 获取各 AU 强度 (归一化到 0-1)
    au1 = facs_state.get_au(FACSActionUnit.AU1) / 5.0  # 内眉上扬
    au2 = facs_state.get_au(FACSActionUnit.AU2) / 5.0  # 外眉上扬
    au4 = facs_state.get_au(FACSActionUnit.AU4) / 5.0  # 眉毛下压
    au5 = facs_state.get_au(FACSActionUnit.AU5) / 5.0  # 上眼睑上扬
    au6 = facs_state.get_au(FACSActionUnit.AU6) / 5.0  # 脸颊上扬
    au7 = facs_state.get_au(FACSActionUnit.AU7) / 5.0  # 眼睑紧缩
    au9 = facs_state.get_au(FACSActionUnit.AU9) / 5.0  # 鼻皱
    au10 = facs_state.get_au(FACSActionUnit.AU10) / 5.0  # 上唇上扬
    au12 = facs_state.get_au(FACSActionUnit.AU12) / 5.0  # 嘴角上扬（微笑）
    au14 = facs_state.get_au(FACSActionUnit.AU14) / 5.0  # 酒窝
    au15 = facs_state.get_au(FACSActionUnit.AU15) / 5.0  # 嘴角下拉
    au17 = facs_state.get_au(FACSActionUnit.AU17) / 5.0  # 下唇上推
    au20 = facs_state.get_au(FACSActionUnit.AU20) / 5.0  # 嘴唇伸展
    au23 = facs_state.get_au(FACSActionUnit.AU23) / 5.0  # 嘴唇收紧
    au24 = facs_state.get_au(FACSActionUnit.AU24) / 5.0  # 嘴唇按压
    au25 = facs_state.get_au(FACSActionUnit.AU25) / 5.0  # 嘴唇分开
    au26 = facs_state.get_au(FACSActionUnit.AU26) / 5.0  # 下颌下拉
    au27 = facs_state.get_au(FACSActionUnit.AU27) / 5.0  # 嘴巴张开
    au43 = facs_state.get_au(FACSActionUnit.AU43) / 5.0  # 眼睛闭合
    au45 = facs_state.get_au(FACSActionUnit.AU45) / 5.0  # 眨眼

    # ---- 眉毛参数 ----
    # 增大系数使表情更明显
    brow_raise = au2 * 1.2 + au1 * 0.6  # 上扬
    brow_lower = au4 * 1.0  # 下压
    params.brow_l_form = brow_raise - brow_lower
    params.brow_r_form = brow_raise - brow_lower

    # AU1 单独作用时产生不对称（困惑/担忧）
    if au1 > au2:
        params.brow_l_form += au1 * 0.3
        params.brow_r_form += au1 * 0.15

    # ---- 眼睛开合参数 ----
    eye_open_base = 1.0
    eye_open_base += au5 * 0.5  # 惊讶时睁大
    eye_open_base -= au7 * 0.6  # 紧张时眯眼
    eye_open_base -= au43 * 0.95  # 闭眼
    eye_open_base -= au45 * 0.95  # 眨眼
    params.eye_l_open = max(0, min(1, eye_open_base))
    params.eye_r_open = max(0, min(1, eye_open_base))

    # ---- 眼睛微笑参数 ----
    params.eye_l_smile = au6 * 1.0
    params.eye_r_smile = au6 * 1.0

    # ---- 脸颊参数 ----
    params.cheek = au6 * 0.6

    # ---- 嘴巴形状参数 ----
    # mouth_form: 负值=圆唇，正值=展唇
    mouth_form = 0
    mouth_form += au12 * 1.0  # 微笑
    mouth_form += au14 * 0.5  # 酒窝
    mouth_form -= au15 * 0.8  # 悲伤下拉
    mouth_form += au20 * 0.6  # 紧张伸展
    mouth_form -= au23 * 0.7  # 生气收紧
    params.mouth_form = max(-1, min(1, mouth_form))

    # ---- 嘴巴开合参数 ----
    mouth_open = 0
    mouth_open += au25 * 0.5  # 微张
    mouth_open += au26 * 0.8  # 下颌下拉
    mouth_open += au27 * 1.0  # 大张
    mouth_open -= au17 * 0.3  # 下唇上推时嘴巴微闭
    mouth_open -= au10 * 0.3  # 上唇上扬时嘴巴微闭
    params.mouth_open = max(0, min(1, mouth_open))

    # 嘴唇按压时嘴巴关闭
    if au24 > 0.3:
        params.mouth_open = max(0, params.mouth_open - au24 * 0.5)

    return params


# ============================================================
# 文本情感分析器
# ============================================================


class TextEmotionAnalyzer:
    """基于关键词和规则的文本情感分析器"""

    # 情感关键词库
    EMOTION_KEYWORDS = {
        "happy": {
            "strong": ["哈哈", "太好了", "开心", "快乐", "高兴", "棒", "厉害", "哇", "耶", "嘻嘻", "嘿嘿"],
            "medium": ["不错", "好的", "嗯嗯", "可以", "喜欢", "爱", "感谢", "谢谢", "赞"],
            "weak": ["还行", "好吧", "嗯"],
            "punctuation": ["~", "～", "!", "！", "😊", "😄", "😆", "❤"],
        },
        "sad": {
            "strong": ["难过", "伤心", "哭", "悲", "惨", "痛苦", "失望", "绝望"],
            "medium": ["唉", "哎", "可惜", "遗憾", "后悔", "想念", "思念"],
            "weak": ["嗯", "哦"],
            "punctuation": ["...", "……", "唉"],
        },
        "angry": {
            "strong": ["生气", "愤怒", "讨厌", "恨", "烦", "滚", "混蛋", "可恶"],
            "medium": ["不爽", "郁闷", "无聊", "烦人"],
            "weak": ["唉"],
            "punctuation": ["!", "！"],
        },
        "surprised": {
            "strong": ["哇", "天哪", "不会吧", "真的吗", "什么", "惊", "吓"],
            "medium": ["哦", "原来", "竟然", "居然"],
            "weak": ["嗯"],
            "punctuation": ["!", "！", "?", "？"],
        },
        "thinking": {
            "strong": ["想想", "思考", "分析", "研究", "为什么", "怎么", "如何"],
            "medium": ["嗯", "这个", "那个", "可能", "也许"],
            "weak": ["呃"],
            "punctuation": ["?", "？", "...", "……"],
        },
        "shy": {
            "strong": ["害羞", "不好意思", "羞", "脸红"],
            "medium": ["嘿嘿", "那个", "人家"],
            "weak": ["嗯"],
            "punctuation": ["~", "～"],
        },
    }

    def analyze(self, text: str) -> dict[str, float]:
        """分析文本情感，返回各情感的置信度 (0-1)"""
        if not text:
            return {"neutral": 1.0}

        scores = {emotion: 0.0 for emotion in self.EMOTION_KEYWORDS}

        # 关键词匹配
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            # 强关键词
            for kw in keywords.get("strong", []):
                if kw in text:
                    scores[emotion] += 0.4

            # 中关键词
            for kw in keywords.get("medium", []):
                if kw in text:
                    scores[emotion] += 0.2

            # 弱关键词
            for kw in keywords.get("weak", []):
                if kw in text:
                    scores[emotion] += 0.05

            # 标点符号
            for p in keywords.get("punctuation", []):
                count = text.count(p)
                if count > 0:
                    scores[emotion] += min(0.3, count * 0.1)

        # 归一化
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        else:
            scores["neutral"] = 1.0

        return scores

    def get_dominant_emotion(self, text: str) -> tuple[str, float]:
        """获取主要情感"""
        scores = self.analyze(text)
        dominant = max(scores, key=scores.get)
        return dominant, scores[dominant]


# ============================================================
# FACS 表情引擎
# ============================================================


class FACSEngine:
    """FACS 表情引擎 - 从文本生成 FACS 表情"""

    def __init__(self):
        self.analyzer = TextEmotionAnalyzer()

    def text_to_facs(self, text: str, intensity_multiplier: float = 1.0) -> FACSState:
        """将文本转换为 FACS 状态"""
        # 分析情感
        emotion_scores = self.analyzer.analyze(text)

        # 混合多个情感的 AU
        combined_state = FACSState()

        for emotion, score in emotion_scores.items():
            if score < 0.1:  # 忽略低置信度情感
                continue

            au_mapping = EMOTION_AU_MAPPINGS.get(emotion, {})
            for au, base_intensity in au_mapping.items():
                current = combined_state.get_au(au)
                # 加权混合
                combined_state.set_au(au, current + base_intensity * score * intensity_multiplier)

        return combined_state

    def text_to_live2d(self, text: str, intensity_multiplier: float = 1.0) -> Live2DParams:
        """将文本转换为 Live2D 参数"""
        facs_state = self.text_to_facs(text, intensity_multiplier)
        return au_to_live2d(facs_state)

    def text_to_dict(self, text: str, intensity_multiplier: float = 1.0) -> dict:
        """将文本转换为 Live2D 参数字典"""
        params = self.text_to_live2d(text, intensity_multiplier)
        return params.to_dict()

    def emotion_to_facs(self, emotion: str, intensity: float = 0.8) -> FACSState:
        """将情感名称转换为 FACS 状态"""
        au_mapping = EMOTION_AU_MAPPINGS.get(emotion, {})
        state = FACSState()
        for au, base_intensity in au_mapping.items():
            state.set_au(au, base_intensity * intensity)
        return state

    def emotion_to_live2d(self, emotion: str, intensity: float = 0.8) -> dict:
        """将情感名称转换为 Live2D 参数字典"""
        facs_state = self.emotion_to_facs(emotion, intensity)
        params = au_to_live2d(facs_state)
        return params.to_dict()


# ============================================================
# 全局引擎实例
# ============================================================

_engine: Optional[FACSEngine] = None


def get_facs_engine() -> FACSEngine:
    """获取全局 FACS 引擎实例"""
    global _engine
    if _engine is None:
        _engine = FACSEngine()
    return _engine


def analyze_text_emotion(text: str) -> dict:
    """分析文本情感，返回 FACS 参数字典"""
    engine = get_facs_engine()
    return engine.text_to_dict(text)


def get_emotion_params(emotion: str, intensity: float = 0.8) -> dict:
    """获取指定情感的 FACS 参数字典"""
    engine = get_facs_engine()
    return engine.emotion_to_live2d(emotion, intensity)
