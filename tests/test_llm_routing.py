"""Unit tests for semantic agent routing decisions."""

from types import SimpleNamespace

import pytest

import modules.llm as llm


def _patch_router_response(monkeypatch: pytest.MonkeyPatch, content: str):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )

    class _Completions:
        @staticmethod
        def create(**kwargs):
            return response

    class _Chat:
        completions = _Completions()

    monkeypatch.setattr(llm, "client", SimpleNamespace(chat=_Chat()))


@pytest.mark.unit
def test_decide_agent_routing_returns_agent_when_semantic_intent_is_action(monkeypatch: pytest.MonkeyPatch):
    _patch_router_response(
        monkeypatch,
        '{"route":"agent","confidence":0.93,"task":"打开浏览器并搜索今日天气","reason":"用户希望执行外部操作"}',
    )

    decision = llm.decide_agent_routing(
        system_prompt="你是一个助手",
        model_name="test-model",
        prompt="帮我查一下今天北京天气",
    )

    assert decision.should_trigger is True
    assert decision.confidence == pytest.approx(0.93)
    assert decision.task == "打开浏览器并搜索今日天气"


@pytest.mark.unit
def test_decide_agent_routing_rejects_low_confidence_trigger(monkeypatch: pytest.MonkeyPatch):
    _patch_router_response(
        monkeypatch,
        '{"route":"agent","confidence":0.40,"task":"打开记事本","reason":"不确定"}',
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
    _patch_router_response(monkeypatch, "我觉得这是聊天，不需要工具")

    decision = llm.decide_agent_routing(
        system_prompt="",
        model_name="test-model",
        prompt="你好呀",
    )

    assert decision.should_trigger is False
    assert "non-json" in decision.reason
