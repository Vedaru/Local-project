"""Unit tests for avatar expression manager behavior."""

from modules.avatar.expression import Emotion, ExpressionManager


def test_default_happy_motion_group_matches_model_group():
    mgr = ExpressionManager(expression_callback=lambda _: None, motion_callback=lambda _g, _i: None)
    cfg = mgr.get_expression_config(Emotion.HAPPY)
    assert cfg is not None
    assert cfg.motion_group == "Tap@Body"


def test_set_emotion_triggers_motion_callback_by_default():
    expression_calls: list[int] = []
    motion_calls: list[tuple[str, int]] = []

    mgr = ExpressionManager(
        expression_callback=lambda idx: expression_calls.append(idx),
        motion_callback=lambda group, index: motion_calls.append((group, index)),
    )

    mgr.set_emotion(Emotion.HAPPY)

    assert expression_calls
    assert motion_calls
    assert motion_calls[-1][0] == "Tap@Body"


def test_set_emotion_can_disable_motion_callback():
    motion_calls: list[tuple[str, int]] = []

    mgr = ExpressionManager(
        expression_callback=lambda _idx: None,
        motion_callback=lambda group, index: motion_calls.append((group, index)),
    )

    mgr.set_emotion(Emotion.HAPPY, play_motion=False)

    assert motion_calls == []
