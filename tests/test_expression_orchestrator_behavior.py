"""Unit tests for expression orchestrator neutral fallback behavior."""

import pytest

from modules.application.expression_orchestrator import ExpressionOrchestrator
from modules.avatar.expression import Emotion


class _DummyExpressionManager:
    def __init__(self, emotion: Emotion):
        self.current_emotion = emotion
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1
        self.current_emotion = Emotion.NEUTRAL

    def set_emotion(self, emotion: Emotion, play_motion: bool = True):
        _ = play_motion
        self.current_emotion = emotion


@pytest.mark.unit
def test_on_expression_change_empty_text_resets_to_neutral():
    manager = _DummyExpressionManager(Emotion.SAD)
    orchestrator = ExpressionOrchestrator(expression_manager=manager, qt_app=None)

    orchestrator.on_expression_change("")

    assert manager.current_emotion == Emotion.NEUTRAL
    assert manager.reset_calls == 1


@pytest.mark.unit
def test_on_expression_change_empty_text_keeps_neutral_without_extra_reset():
    manager = _DummyExpressionManager(Emotion.NEUTRAL)
    orchestrator = ExpressionOrchestrator(expression_manager=manager, qt_app=None)

    orchestrator.on_expression_change("   ")

    assert manager.current_emotion == Emotion.NEUTRAL
    assert manager.reset_calls == 0
