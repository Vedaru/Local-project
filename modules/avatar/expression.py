"""
表情管理模块 - 基于文本情感分析的表情控制

NOTE: Several methods and dataclasses in this module are part of the public
Avatar expression API and may be called dynamically by the Avatar manager or
external code. Keep public method signatures stable to preserve compatibility.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .logger import log_debug, log_info


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
class ExpressionTimelinePoint:
    """分段表情时间线节点。"""

    offset_sec: float
    emotion: Emotion
    confidence: float
    segment: str


class EmotionAnalyzer:
    """情感分析器 - 基于结构信号与权重融合分析情感。"""

    def __init__(self, keywords: Optional[object] = None):
        _ = keywords  # 保留参数兼容性

        # 标点符号的情感倾向权重
        self._punctuation_weights = {
            "！": 0.3, "!": 0.3,
            "？": -0.15, "?": -0.15,
            "...": -0.15, "……": -0.15,
            "~": 0.15, "～": 0.15,
        }

    def split_segments(self, text: str) -> list[str]:
        """按语义停顿切分句段，用于动态表情时间线。"""
        normalized = (text or "").strip()
        if not normalized:
            return []

        major_segments = [
            segment.strip()
            for segment in re.split(r"(?<=[。！？!?；;…])|[\r\n]+", normalized)
            if segment and segment.strip()
        ]

        # Expand long clauses by minor pauses so each spoken phrase can get its own expression point.
        expanded_segments: list[str] = []
        for segment in major_segments:
            if len(segment) >= 16 and re.search(r"[，,、：:]", segment):
                expanded_segments.extend(
                    piece.strip()
                    for piece in re.split(r"(?<=[，,、：:])", segment)
                    if piece and piece.strip()
                )
            else:
                expanded_segments.append(segment)

        # Merge tiny fragments to avoid over-fragmenting into jittery micro-segments.
        segments: list[str] = []
        for piece in expanded_segments:
            if segments and len(piece) <= 4:
                segments[-1] = f"{segments[-1]}{piece}"
            else:
                segments.append(piece)

        return segments or [normalized]

    def score_weights(self, text: str) -> dict[Emotion, float]:
        """输出每个情感的归一化权重（总和为 1）。"""
        if not text:
            return {emotion: (1.0 if emotion == Emotion.NEUTRAL else 0.0) for emotion in Emotion}

        text_len = len(text)
        punctuation_question = text.count("？") + text.count("?")
        punctuation_exclaim = text.count("！") + text.count("!")
        punctuation_ellipsis = text.count("...") + text.count("……")
        punctuation_tilde = text.count("~") + text.count("～")
        punctuation_minor_pause = sum(text.count(token) for token in ("，", ",", "、", "：", ":", "；", ";"))

        segments = self.split_segments(text)
        segment_count = max(1, len(segments))
        average_segment_len = text_len / segment_count

        short_segments = sum(1 for segment in segments if len(segment.strip()) <= 8)
        cadence_density = segment_count / max(1.0, text_len / 8.0)

        energy_signal = min(
            1.8,
            punctuation_exclaim * 0.34
            + punctuation_tilde * 0.26
            + punctuation_minor_pause * 0.04
            + max(0, segment_count - 1) * 0.05,
        )
        uncertainty_signal = min(
            1.8,
            punctuation_question * 0.30
            + punctuation_ellipsis * 0.26
            + max(0.0, (average_segment_len - 16.0) * 0.012),
        )
        staccato_signal = min(
            1.5,
            short_segments * 0.16
            + max(0, segment_count - 2) * 0.08
            + cadence_density * 0.18,
        )
        playful_signal = min(1.7, punctuation_tilde * 0.48 + punctuation_exclaim * 0.16 + max(0.0, 0.16 - punctuation_ellipsis * 0.05))
        aggression_signal = max(
            0.0,
            punctuation_exclaim * 0.24
            + staccato_signal * 0.28
            + max(0, punctuation_exclaim - punctuation_question) * 0.12
            - punctuation_tilde * 0.26
            - punctuation_ellipsis * 0.08,
        )

        final_happy = max(0.0, playful_signal + energy_signal * 0.30 - uncertainty_signal * 0.22 - aggression_signal * 0.35)
        final_sad = max(0.0, punctuation_ellipsis * 0.34 + max(0.0, 0.20 - energy_signal * 0.10) + max(0.0, uncertainty_signal - playful_signal) * 0.08)
        final_angry = max(0.0, aggression_signal + punctuation_exclaim * 0.10 + max(0.0, staccato_signal - 0.3) * 0.15)
        final_surprised = max(0.0, min(punctuation_exclaim, punctuation_question) * 0.42 + punctuation_exclaim * 0.08 + punctuation_question * 0.08)

        # 问句默认偏思考，只有在高不确定+低愉悦时才提升困惑。
        final_thinking = max(
            0.0,
            uncertainty_signal * 0.48
            + (0.22 if punctuation_question > 0 else 0.0)
            + (0.12 if punctuation_ellipsis > 0 else 0.0)
            - energy_signal * 0.10,
        )
        final_confused = max(
            0.0,
            punctuation_question * 0.10
            + punctuation_ellipsis * 0.12
            + max(0.0, uncertainty_signal - playful_signal - 0.35) * 0.22
            - playful_signal * 0.14,
        )
        final_shy = max(0.0, 0.04 + (0.10 if text_len <= 12 else 0.0) + (0.06 if punctuation_tilde > 0 and punctuation_exclaim == 0 else 0.0) - punctuation_exclaim * 0.05)
        final_neutral = max(
            0.10,
            0.24 + max(0.0, 0.10 - (final_happy + final_sad + final_angry + final_surprised + final_confused + final_thinking) * 0.03),
        )

        raw_scores = {
            Emotion.HAPPY: final_happy,
            Emotion.SAD: final_sad,
            Emotion.ANGRY: final_angry,
            Emotion.SURPRISED: final_surprised,
            Emotion.SHY: final_shy,
            Emotion.CONFUSED: final_confused,
            Emotion.THINKING: final_thinking,
            Emotion.NEUTRAL: final_neutral,
        }

        clipped_scores: dict[Emotion, float] = {}
        for emotion, value in raw_scores.items():
            if emotion == Emotion.NEUTRAL:
                clipped_scores[emotion] = max(0.05, value)
            else:
                clipped_scores[emotion] = max(0.0, value)

        total = sum(clipped_scores.values())
        if total <= 1e-6:
            return {emotion: (1.0 if emotion == Emotion.NEUTRAL else 0.0) for emotion in Emotion}

        return {emotion: clipped_scores[emotion] / total for emotion in Emotion}

    def analyze(self, text: str) -> tuple[Emotion, float]:
        """返回主情感与置信度。"""
        weights = self.score_weights(text)
        max_emotion = max(weights, key=weights.get)
        max_weight = weights[max_emotion]

        if max_emotion == Emotion.NEUTRAL or max_weight < 0.24:
            return Emotion.NEUTRAL, 0.0

        confidence = min(1.0, max_weight * 1.6)
        log_debug(f"Semantic emotion: {max_emotion.value} ({confidence:.2f}, weight={max_weight:.2f})")
        return max_emotion, confidence


class ExpressionManager:
    """表情管理器 - 管理和控制 Live2D 模型的表情"""

    # 默认表情配置
    DEFAULT_EXPRESSIONS: dict[Emotion, ExpressionConfig] = {
        Emotion.NEUTRAL: ExpressionConfig(Emotion.NEUTRAL, 0, "Idle", 0, 1),
        Emotion.HAPPY: ExpressionConfig(Emotion.HAPPY, 2, "Tap@Body", 0, 2),
        Emotion.SAD: ExpressionConfig(Emotion.SAD, 3, "FlickDown", 0, 2),
        Emotion.ANGRY: ExpressionConfig(Emotion.ANGRY, 4, "Flick@Body", 0, 3),
        Emotion.SURPRISED: ExpressionConfig(Emotion.SURPRISED, 5, "Flick", 0, 3),
        Emotion.THINKING: ExpressionConfig(Emotion.THINKING, 1, "Tap", 0, 1),
        Emotion.SHY: ExpressionConfig(Emotion.SHY, 6, "Tap", 0, 2),
        Emotion.CONFUSED: ExpressionConfig(Emotion.CONFUSED, 7, "Flick", 0, 1),
    }

    def __init__(
        self,
        expression_callback: Callable[[int], None],
        motion_callback: Optional[Callable[[str, int], None]] = None,
        expression_config: Optional[dict[Emotion, ExpressionConfig]] = None,
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

    def build_weighted_timeline(
        self,
        text: str,
        duration_sec: Optional[float] = None,
        max_segments: int = 8,
    ) -> list[ExpressionTimelinePoint]:
        """基于分段文本权重生成动态表情时间线。"""
        normalized_text = (text or "").strip()
        if not normalized_text:
            return [ExpressionTimelinePoint(offset_sec=0.0, emotion=Emotion.NEUTRAL, confidence=1.0, segment="")]

        segments = self._analyzer.split_segments(normalized_text)
        max_segments = max(1, int(max_segments))
        if len(segments) > max_segments:
            kept = segments[: max_segments - 1]
            kept.append(" ".join(segments[max_segments - 1 :]))
            segments = kept

        # 从 TuningConfig 读取情感分析参数（替代散落的 os.getenv）
        try:
            from modules.config import get_tuning
            _expr_tuning = get_tuning().expression
            min_segment_sec = max(0.12, min(0.8, _expr_tuning.min_segment_sec))
            min_hold_sec = max(0.2, min(1.5, _expr_tuning.min_hold_sec))
            switch_margin = max(0.02, min(0.35, _expr_tuning.switch_margin))
            continuity_bias = max(0.0, min(0.30, _expr_tuning.continuity_bias))
            smooth_window_sec = max(0.15, min(1.2, _expr_tuning.smooth_window_sec))
            tail_neutral_sec = max(0.12, min(1.0, _expr_tuning.neutral_tail_sec))
        except Exception:
            min_segment_sec = 0.30
            min_hold_sec = 0.55
            switch_margin = 0.10
            continuity_bias = 0.12
            smooth_window_sec = 0.55
            tail_neutral_sec = 0.26

        total_chars = max(1, sum(len(segment) for segment in segments))
        min_total_duration = max(1.2, len(segments) * min_segment_sec)
        if duration_sec is None or duration_sec <= 0:
            duration_sec = max(min_total_duration, min(10.0, total_chars * 0.12))
        else:
            duration_sec = max(duration_sec, min_total_duration)

        raw_durations = [max(min_segment_sec, duration_sec * (len(segment) / total_chars)) for segment in segments]
        raw_total = sum(raw_durations) or 1.0
        scale = duration_sec / raw_total
        durations = [segment_duration * scale for segment_duration in raw_durations]

        timeline: list[ExpressionTimelinePoint] = []
        carry = {emotion: 0.0 for emotion in Emotion}
        carry[Emotion.NEUTRAL] = 1.0
        offset = 0.0

        # min_hold_sec, switch_margin, continuity_bias 已在上方从 TuningConfig 统一读取

        previous_selected: Optional[Emotion] = None
        previous_selected_offset = 0.0

        for segment, segment_duration in zip(segments, durations):
            weights = self._analyzer.score_weights(segment)
            blended = {
                emotion: weights.get(emotion, 0.0) * 0.72 + carry.get(emotion, 0.0) * 0.28
                for emotion in Emotion
            }

            if previous_selected is not None:
                blended[previous_selected] = blended.get(previous_selected, 0.0) + continuity_bias
                if previous_selected != Emotion.NEUTRAL:
                    blended[Emotion.NEUTRAL] = blended.get(Emotion.NEUTRAL, 0.0) * 0.92

            selected = max(blended, key=blended.get)
            confidence = blended[selected]
            if confidence < 0.22:
                selected = Emotion.NEUTRAL
                confidence = blended.get(Emotion.NEUTRAL, 0.0)

            if previous_selected is not None and selected != previous_selected:
                previous_score = blended.get(previous_selected, 0.0)
                score_gap = confidence - previous_score
                elapsed_sec = max(0.0, offset - previous_selected_offset)

                if elapsed_sec < min_hold_sec and score_gap < switch_margin:
                    selected = previous_selected
                    confidence = previous_score
                elif previous_selected != Emotion.NEUTRAL and score_gap < (switch_margin * 0.55):
                    selected = previous_selected
                    confidence = previous_score

            # Preserve every segment point so each segment can trigger a visible expression update.
            timeline.append(
                ExpressionTimelinePoint(
                    offset_sec=offset,
                    emotion=selected,
                    confidence=confidence,
                    segment=segment,
                )
            )

            carry = blended
            if selected != previous_selected:
                previous_selected = selected
                previous_selected_offset = offset
            offset += segment_duration

        if not timeline:
            timeline.append(ExpressionTimelinePoint(offset_sec=0.0, emotion=Emotion.NEUTRAL, confidence=1.0, segment=""))

        # smooth_window_sec 已在上方从 TuningConfig 统一读取

        # Smooth out short neutral flashes or low-confidence spikes between same neighboring emotions.
        if len(timeline) >= 3:
            for idx in range(1, len(timeline) - 1):
                prev_point = timeline[idx - 1]
                curr_point = timeline[idx]
                next_point = timeline[idx + 1]

                left_gap = max(0.0, curr_point.offset_sec - prev_point.offset_sec)
                right_gap = max(0.0, next_point.offset_sec - curr_point.offset_sec)
                if left_gap > smooth_window_sec or right_gap > smooth_window_sec:
                    continue

                if (
                    curr_point.emotion == Emotion.NEUTRAL
                    and prev_point.emotion == next_point.emotion
                    and prev_point.emotion != Emotion.NEUTRAL
                ):
                    curr_point.emotion = prev_point.emotion
                    curr_point.confidence = max(
                        curr_point.confidence,
                        min(prev_point.confidence, next_point.confidence) * 0.9,
                    )
                    continue

                if prev_point.emotion == next_point.emotion and curr_point.emotion != prev_point.emotion:
                    neighbor_conf = max(prev_point.confidence, next_point.confidence)
                    if curr_point.confidence + 0.10 < neighbor_conf:
                        curr_point.emotion = prev_point.emotion
                        curr_point.confidence = max(curr_point.confidence, neighbor_conf * 0.85)

        min_gap_sec = max(0.08, min_segment_sec * 0.72)
        for idx in range(1, len(timeline)):
            required_offset = timeline[idx - 1].offset_sec + min_gap_sec
            if timeline[idx].offset_sec < required_offset:
                timeline[idx].offset_sec = required_offset

        # tail_neutral_sec 已在上方从 TuningConfig 统一读取

        if timeline[-1].emotion != Emotion.NEUTRAL:
            timeline.append(
                ExpressionTimelinePoint(
                    offset_sec=max(duration_sec + tail_neutral_sec, timeline[-1].offset_sec + tail_neutral_sec),
                    emotion=Emotion.NEUTRAL,
                    confidence=1.0,
                    segment="",
                )
            )

        log_debug(
            f"Weighted timeline built: segments={len(segments)} points={len(timeline)} "
            f"duration={duration_sec:.2f}s min_gap={min_gap_sec:.2f}s"
        )

        return timeline

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
                    config.motion_group, config.motion_index if config.motion_index is not None else 0
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
        weights = self._analyzer.score_weights(text)
        emotion = max(weights, key=weights.get)
        confidence = weights[emotion]

        if emotion != Emotion.NEUTRAL and confidence >= 0.24:
            self.set_emotion(emotion, play_motion=play_motion)
            return emotion

        if self._current_emotion != Emotion.NEUTRAL:
            self.set_emotion(Emotion.NEUTRAL, play_motion=False)
        return Emotion.NEUTRAL

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
