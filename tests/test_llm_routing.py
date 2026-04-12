"""Unit tests for semantic agent routing decisions."""

from types import SimpleNamespace

import pytest

import modules.llm as llm


def _patch_router_responses(
    monkeypatch: pytest.MonkeyPatch,
    contents: list[str],
    captured_kwargs: list[dict] | None = None,
):
    queue = list(contents)

    class _Completions:
        @staticmethod
        def create(**kwargs):
            if captured_kwargs is not None:
                captured_kwargs.append(dict(kwargs))
            if not queue:
                raise AssertionError("no mocked router response left")
            content = queue.pop(0)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            )

    class _Chat:
        completions = _Completions()

    monkeypatch.setattr(llm, "client", SimpleNamespace(chat=_Chat()))


@pytest.mark.unit
def test_decide_agent_routing_returns_agent_when_semantic_intent_is_action(monkeypatch: pytest.MonkeyPatch):
    _patch_router_responses(
        monkeypatch,
        ['{"route":"agent","confidence":0.93,"task":"打开浏览器并搜索今日天气","reason":"用户希望执行外部操作","is_atomic":true}'],
    )

    decision = llm.decide_agent_routing(
        system_prompt="你是一个助手",
        model_name="test-model",
        prompt="帮我查一下今天北京天气",
    )

    assert decision.should_trigger is True
    assert decision.confidence == pytest.approx(0.93)
    assert decision.task == "打开浏览器并搜索今日天气"
    assert decision.is_atomic is True


@pytest.mark.unit
def test_decide_agent_routing_rejects_low_confidence_trigger(monkeypatch: pytest.MonkeyPatch):
    _patch_router_responses(
        monkeypatch,
        ['{"route":"agent","confidence":0.40,"task":"打开记事本","reason":"不确定","is_atomic":true}'],
    )

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="你觉得我要不要做计划",
        min_confidence=0.65,
    )

    assert decision.should_trigger is False
    assert decision.task == ""


@pytest.mark.unit
def test_decide_agent_routing_falls_back_to_chat_on_invalid_json(monkeypatch: pytest.MonkeyPatch):
    _patch_router_responses(
        monkeypatch,
        [
            "我觉得这是聊天，不需要工具",
            "仍然不是 JSON",
        ],
    )

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="你好呀",
    )

    assert decision.should_trigger is False
    assert "non-json" in decision.reason


@pytest.mark.unit
def test_decide_agent_routing_dual_validation_can_correct_to_chat(monkeypatch: pytest.MonkeyPatch):
    _patch_router_responses(
        monkeypatch,
        [
            '{"route":"agent","confidence":0.72,"task":"打开浏览器","reason":"像是工具请求","is_atomic":true}',
            '{"route":"chat","confidence":0.86,"reason":"更像闲聊提问"}',
        ],
    )

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="你觉得我今天心情怎么样",
    )

    assert decision.should_trigger is False
    assert "闲聊" in decision.reason or "chat" in decision.reason.lower()


@pytest.mark.unit
def test_decide_agent_routing_retry_uses_strict_json_mode(monkeypatch: pytest.MonkeyPatch):
    captured_kwargs: list[dict] = []
    _patch_router_responses(
        monkeypatch,
        [
            "not-json",
            '{"route":"chat","confidence":0.9,"task":"","reason":"ok","is_atomic":true}',
        ],
        captured_kwargs=captured_kwargs,
    )

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="你好",
        max_retries=1,
    )

    assert decision.should_trigger is False
    assert len(captured_kwargs) >= 2
    assert "response_format" not in captured_kwargs[0]
    assert captured_kwargs[1].get("response_format") == {"type": "json_object"}


@pytest.mark.unit
def test_decide_agent_routing_rejects_non_atomic_task(monkeypatch: pytest.MonkeyPatch):
    _patch_router_responses(
        monkeypatch,
        ['{"route":"agent","confidence":0.91,"task":"请同时打开并关闭这个服务","reason":"执行任务","is_atomic":true}'],
    )

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="同时把服务打开并关闭",
    )

    assert decision.should_trigger is False
    assert decision.is_atomic is False
