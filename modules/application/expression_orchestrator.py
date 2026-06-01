"""
ExpressionOrchestrator — 表情/情绪时间线管理 + 定时器调度

从 LocalProjectApplication 中提取，负责:
- 表情时间线的构建与调度（加权情感分析 → 定时器驱动）
- 情绪衰减定时器
- 表情状态追踪
- 配置收敛：从 TuningConfig 读取参数，替代散落 os.getenv
"""

import time
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from modules.avatar import Emotion, ExpressionManager
from modules.config import get_tuning
from modules.logging_config import get_logger
from modules.utils import sanitize_dialogue_text

logger = get_logger("ExpressionOrchestrator")


class ExpressionOrchestrator:
    """Manages expression timeline, emotion decay, and weighted expression scheduling."""

    def __init__(self, expression_manager: ExpressionManager, qt_app: QApplication, tuning=None):
        self._expression_manager = expression_manager
        self._app = qt_app
        # 从 TuningConfig 读取表情调优参数
        t = (tuning or get_tuning()).expression
        self._auto_reset_sec: float = t.auto_reset_sec
        self._min_timer_gap_ms: int = t.min_timer_gap_ms
        self._timeline_play_motion: bool = t.timeline_play_motion

        # 表情定时器列表（用于清理）
        self._expression_timers: list[QTimer] = []
        # 情绪衰减定时器
        self._emotion_decay_timer: Optional[QTimer] = None
        # 待处理的表达文本
        self._pending_expression_text = ""
        # 上次用于表情种子的文本和时间
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0

    @property
    def expression_manager(self) -> Optional[ExpressionManager]:
        return self._expression_manager

    @property
    def pending_expression_text(self) -> str:
        return self._pending_expression_text

    @pending_expression_text.setter
    def pending_expression_text(self, value: str):
        self._pending_expression_text = value

    @property
    def last_expression_seed_text(self) -> str:
        return self._last_expression_seed_text

    @property
    def last_expression_seed_at(self) -> float:
        return self._last_expression_seed_at

    def on_expression_change(self, expression) -> None:
        """Handle incoming expression change signal/event."""
        if not self._expression_manager:
            return

        if isinstance(expression, Emotion):
            self._clear_expression_timers()
            self._expression_manager.set_emotion(expression)
            if expression != Emotion.NEUTRAL:
                self._schedule_emotion_decay()
            return

        analyzable_text = ""
        if isinstance(expression, dict):
            analyzable_text = sanitize_dialogue_text(str(expression.get("text") or expression.get("answer") or ""))
        elif isinstance(expression, str):
            analyzable_text = sanitize_dialogue_text(expression)
        else:
            return

        if analyzable_text:
            self._pending_expression_text = analyzable_text
            self._start_weighted_expression_flow(analyzable_text, duration_sec=None)
            return

        # 清洗后为空（例如仅剩标签/控制字符）时，主动回中性，避免卡在上一轮情绪。
        self._pending_expression_text = ""
        self._clear_expression_timers()
        if self._expression_manager.current_emotion != Emotion.NEUTRAL:
            self._expression_manager.reset()

    def _apply_expression_change(self, emotion: Emotion) -> None:
        if self._expression_manager:
            self._expression_manager.set_emotion(emotion, play_motion=self._timeline_play_motion)

    def _clear_expression_timers(self):
        for timer in self._expression_timers:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._expression_timers.clear()

        if self._emotion_decay_timer is not None:
            try:
                self._emotion_decay_timer.stop()
                self._emotion_decay_timer.deleteLater()
            except Exception:
                pass
            self._emotion_decay_timer = None

    def _schedule_emotion_decay(self, delay_sec: Optional[float] = None) -> None:
        if not self._expression_manager:
            return

        current = self._expression_manager.current_emotion
        if current == Emotion.NEUTRAL:
            return

        if delay_sec is None:
            delay_sec = self._auto_reset_sec

        delay_sec = max(0.3, float(delay_sec))

        if self._emotion_decay_timer is not None:
            try:
                self._emotion_decay_timer.stop()
                self._emotion_decay_timer.deleteLater()
            except Exception:
                pass
            self._emotion_decay_timer = None

        target_emotion = current
        timer = QTimer(self._app)
        timer.setSingleShot(True)

        def _decay_to_neutral() -> None:
            if not self._expression_manager:
                return
            if self._expression_manager.current_emotion == target_emotion and target_emotion != Emotion.NEUTRAL:
                self._expression_manager.reset()
            if self._emotion_decay_timer is timer:
                self._emotion_decay_timer = None

        timer.timeout.connect(_decay_to_neutral)
        timer.start(int(delay_sec * 1000))
        self._emotion_decay_timer = timer

    def _start_weighted_expression_flow(self, text: str, duration_sec: Optional[float]) -> None:
        if not self._expression_manager:
            return

        cleaned = sanitize_dialogue_text(text)
        self._clear_expression_timers()
        if not cleaned:
            self._expression_manager.reset()
            return

        self._last_expression_seed_text = cleaned
        self._last_expression_seed_at = time.monotonic()

        timeline = self._expression_manager.build_weighted_timeline(cleaned, duration_sec=duration_sec)
        if not timeline:
            self._expression_manager.reset()
            return

        preview = ", ".join(f"{point.emotion.value}@{point.offset_sec:.2f}" for point in timeline[:8])
        logger.debug(f"[Expression] 时间线 points={len(timeline)} preview={preview}")

        min_timer_gap_ms: int = max(40, self._min_timer_gap_ms)

        last_delay_ms = -min_timer_gap_ms

        for point in timeline:
            delay_ms = max(0, int(point.offset_sec * 1000))

            if delay_ms > 0 and delay_ms <= last_delay_ms:
                delay_ms = last_delay_ms + min_timer_gap_ms

            if delay_ms == 0 and last_delay_ms >= 0:
                delay_ms = last_delay_ms + min_timer_gap_ms

            if delay_ms == 0:
                self._apply_expression_change(point.emotion)
                last_delay_ms = 0
                continue

            timer = QTimer(self._app)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda emotion=point.emotion: self._apply_expression_change(emotion))
            timer.start(delay_ms)
            self._expression_timers.append(timer)
            last_delay_ms = delay_ms

    def cleanup(self):
        self._clear_expression_timers()
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0
