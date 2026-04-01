"""Unit tests for ManusAgent wrapper behavior."""

import asyncio
from collections.abc import Generator

import pytest

import modules.agent.core as agent_core
from modules.agent.core import ManusAgent


@pytest.fixture
def lightweight_agent(monkeypatch: pytest.MonkeyPatch) -> Generator[ManusAgent, None, None]:
    """Create a lightweight ManusAgent instance without starting real OpenManus runtime."""
    monkeypatch.setattr(agent_core, "_sync_openmanus_config", lambda: None)
    monkeypatch.setattr(ManusAgent, "_start_event_loop", lambda self: None)

    agent = ManusAgent(system_prompt="", max_steps=3, task_timeout_seconds=1.0)
    yield agent
    agent.cleanup()


@pytest.mark.unit
def test_normalize_result_handles_empty_values():
    assert ManusAgent._normalize_result(None) == "⚠️ Agent 未返回有效结果"
    assert ManusAgent._normalize_result("   ") == "⚠️ Agent 未返回有效结果"


@pytest.mark.unit
def test_run_task_rejects_empty_description(lightweight_agent: ManusAgent, monkeypatch: pytest.MonkeyPatch):
    called = False

    def fake_run_coro(coro, timeout=None):
        nonlocal called
        called = True
        coro.close()
        return "should-not-happen"

    monkeypatch.setattr(lightweight_agent, "_run_coro", fake_run_coro)

    result = lightweight_agent.run_task("   ")
    assert result == "⚠️ 无任务描述"
    assert called is False


@pytest.mark.unit
def test_run_task_returns_timeout_message(lightweight_agent: ManusAgent, monkeypatch: pytest.MonkeyPatch):
    def fake_run_coro(coro, timeout=None):
        coro.close()
        raise TimeoutError("timed out")

    monkeypatch.setattr(lightweight_agent, "_run_coro", fake_run_coro)

    result = lightweight_agent.run_task("打开记事本")
    assert "执行超时" in result


@pytest.mark.unit
def test_run_task_normalizes_non_string_result(lightweight_agent: ManusAgent, monkeypatch: pytest.MonkeyPatch):
    async def fake_async_run_task(self, task_description: str):
        return {"status": "ok", "task": task_description}

    def fake_run_coro(coro, timeout=None):
        return asyncio.run(coro)

    monkeypatch.setattr(ManusAgent, "_async_run_task", fake_async_run_task)
    monkeypatch.setattr(lightweight_agent, "_run_coro", fake_run_coro)

    result = lightweight_agent.run_task("执行测试任务")
    assert "status" in result
    assert "执行测试任务" in result
