"""Validation tests for microservices.agent_service.main."""

import pytest
from pydantic import ValidationError

from microservices.agent_service import main as agent_main


class TestExecuteRequestValidation:
    def test_normalizes_user_id_and_task(self):
        req = agent_main.ExecuteRequest(task="  hello  ", user_id="User_A")
        assert req.task == "hello"
        assert req.user_id == "user_a"

    def test_rejects_invalid_priority(self):
        with pytest.raises(ValidationError):
            agent_main.ExecuteRequest(task="hello", priority="urgent")

    def test_rejects_dangerous_task_pattern(self):
        with pytest.raises(ValidationError):
            agent_main.ExecuteRequest(task="run this; rm -rf /", user_id="tester")

    def test_rejects_invalid_user_id(self):
        with pytest.raises(ValidationError):
            agent_main.ExecuteRequest(task="hello", user_id="bad user")


class TestInputValidator:
    def test_validate_url_accepts_http_https(self):
        assert agent_main.InputValidator.validate_url("https://example.com") == "https://example.com"
        assert agent_main.InputValidator.validate_url("http://example.com/a") == "http://example.com/a"

    def test_validate_url_rejects_non_http_scheme(self):
        with pytest.raises(ValueError):
            agent_main.InputValidator.validate_url("file:///tmp/a")

    def test_sanitize_path_rejects_empty(self):
        with pytest.raises(ValueError):
            agent_main.InputValidator.sanitize_path("   ")


@pytest.mark.asyncio
async def test_execute_fallback_mode_when_agent_missing(monkeypatch):
    monkeypatch.setattr(agent_main, "_REAL_AGENT", None)
    req = agent_main.ExecuteRequest(task="hello", user_id="User_A")

    payload = await agent_main.execute(req)
    assert payload["mode"] == "fallback-echo"
    assert "user_a" in payload["result"]
