"""
Tests for modules/llm.py — LLM routing and helpers

Covers:
- AgentRoutingDecision dataclass
- Text normalization helpers
- Routing message construction
- Mutual exclusion detection
- Backoff delay computation
- TimedCache behavior
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from modules.llm import (
    AgentRoutingDecision,
    TimedCache,
    _build_routing_messages,
    _compute_backoff_delay,
    _has_mutually_exclusive_goals,
    _normalize_bool,
    _normalize_confidence,
    _normalize_text,
    _parse_agent_routing_decision,
)

# ============================================================
# AgentRoutingDecision Tests
# ============================================================


class TestAgentRoutingDecision:
    """Test AgentRoutingDecision dataclass."""

    def test_default_values(self):
        decision = AgentRoutingDecision()
        assert decision.should_trigger is False
        assert decision.confidence == 0.0
        assert decision.task == ""
        assert decision.reason == ""
        assert decision.is_atomic is True

    def test_frozen(self):
        decision = AgentRoutingDecision(should_trigger=True)
        with pytest.raises(AttributeError):
            decision.should_trigger = False


# ============================================================
# Text Normalization Tests
# ============================================================


class TestNormalizeText:
    """Test _normalize_text helper."""

    def test_none_returns_default(self):
        assert _normalize_text(None) == ""
        assert _normalize_text(None, default="N/A") == "N/A"

    def test_empty_string(self):
        assert _normalize_text("") == ""
        assert _normalize_text("  ") == ""

    def test_normal_text(self):
        assert _normalize_text("hello") == "hello"
        assert _normalize_text("  hello  ") == "hello"

    def test_non_string(self):
        assert _normalize_text(123) == "123"
        assert _normalize_text(0) == "0"


class TestNormalizeConfidence:
    """Test _normalize_confidence helper."""

    def test_valid_float(self):
        assert _normalize_confidence(0.5) == 0.5
        assert _normalize_confidence(1.0) == 1.0
        assert _normalize_confidence(0.0) == 0.0

    def test_clamp_negative(self):
        assert _normalize_confidence(-0.5) == 0.0

    def test_clamp_above_one(self):
        assert _normalize_confidence(1.5) == 1.0

    def test_invalid_returns_zero(self):
        assert _normalize_confidence("abc") == 0.0
        assert _normalize_confidence(None) == 0.0

    def test_string_number(self):
        assert _normalize_confidence("0.8") == 0.8


class TestNormalizeBool:
    """Test _normalize_bool helper."""

    def test_bool_passthrough(self):
        assert _normalize_bool(True) is True
        assert _normalize_bool(False) is False

    def test_truthy_strings(self):
        assert _normalize_bool("true") is True
        assert _normalize_bool("1") is True
        assert _normalize_bool("yes") is True
        assert _normalize_bool("on") is True

    def test_falsy_strings(self):
        assert _normalize_bool("false") is False
        assert _normalize_bool("0") is False
        assert _normalize_bool("no") is False
        assert _normalize_bool("off") is False

    def test_int_values(self):
        assert _normalize_bool(1) is True
        assert _normalize_bool(0) is False

    def test_default(self):
        assert _normalize_bool("unknown", default=True) is True
        assert _normalize_bool("unknown", default=False) is False


# ============================================================
# Mutual Exclusion Tests
# ============================================================


class TestMutualExclusion:
    """Test _has_mutually_exclusive_goals."""

    def test_no_exclusion(self):
        assert _has_mutually_exclusive_goals("打开浏览器") is False

    def test_chinese_exclusion(self):
        assert _has_mutually_exclusive_goals("打开并关闭浏览器") is True
        assert _has_mutually_exclusive_goals("启用和禁用网络") is True

    def test_english_exclusion(self):
        assert _has_mutually_exclusive_goals("create and delete file") is True
        assert _has_mutually_exclusive_goals("enable and disable service") is True

    def test_empty_task(self):
        assert _has_mutually_exclusive_goals("") is False
        assert _has_mutually_exclusive_goals(None) is False


# ============================================================
# Backoff Delay Tests
# ============================================================


class TestBackoffDelay:
    """Test _compute_backoff_delay."""

    def test_first_attempt(self):
        delay = _compute_backoff_delay(0)
        assert delay == 1.0  # EXPONENTIAL_BACKOFF_BASE_DELAY

    def test_exponential_growth(self):
        delay1 = _compute_backoff_delay(1)
        delay2 = _compute_backoff_delay(2)
        assert delay2 > delay1

    def test_max_delay_cap(self):
        delay = _compute_backoff_delay(100)
        assert delay <= 60.0  # EXPONENTIAL_BACKOFF_MAX_DELAY

    def test_negative_attempt(self):
        delay = _compute_backoff_delay(-1)
        assert delay == 1.0


# ============================================================
# TimedCache Tests
# ============================================================


class TestTimedCache:
    """Test TimedCache behavior."""

    def test_miss(self):
        cache = TimedCache[str](ttl_seconds=10.0)
        assert cache.get(123) is None

    def test_hit(self):
        cache = TimedCache[str](ttl_seconds=10.0)
        cache.set(123, "value")
        assert cache.get(123) == "value"

    def test_expiry(self):
        cache = TimedCache[str](ttl_seconds=0.1)
        cache.set(123, "value")
        time.sleep(0.15)
        assert cache.get(123) is None

    def test_clear(self):
        cache = TimedCache[str](ttl_seconds=10.0)
        cache.set(1, "a")
        cache.set(2, "b")
        cache.clear()
        assert cache.get(1) is None
        assert cache.get(2) is None


# ============================================================
# Routing Message Construction Tests
# ============================================================


class TestRoutingMessages:
    """Test _build_routing_messages."""

    def test_basic_structure(self):
        messages = _build_routing_messages(
            routing_instruction="instruction",
            system_prompt="",
            prompt="hello",
            memory_context="",
        )
        assert len(messages) == 2  # instruction + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_with_system_prompt(self):
        messages = _build_routing_messages(
            routing_instruction="instruction",
            system_prompt="you are helpful",
            prompt="hello",
            memory_context="",
        )
        assert len(messages) == 3

    def test_with_memory_context(self):
        messages = _build_routing_messages(
            routing_instruction="instruction",
            system_prompt="",
            prompt="hello",
            memory_context="some memory",
        )
        assert len(messages) == 3

    def test_with_all_context(self):
        messages = _build_routing_messages(
            routing_instruction="instruction",
            system_prompt="you are helpful",
            prompt="hello",
            memory_context="some memory",
        )
        assert len(messages) == 4


# ============================================================
# Routing Decision Parsing Tests
# ============================================================


class TestRoutingDecisionParsing:
    """Test _parse_agent_routing_decision."""

    def test_invalid_json(self):
        decision, error = _parse_agent_routing_decision("not json", "fallback", 0.65)
        assert decision.should_trigger is False
        assert "non-json" in error

    def test_chat_route(self):
        import json

        raw = json.dumps({"route": "chat", "confidence": 0.9, "reason": "text only"})
        decision, error = _parse_agent_routing_decision(raw, "fallback", 0.65)
        assert decision.should_trigger is False
        assert error == ""

    def test_agent_route_high_confidence(self):
        import json

        raw = json.dumps(
            {
                "route": "agent",
                "confidence": 0.9,
                "task": "open browser",
                "reason": "tool needed",
                "is_atomic": True,
            }
        )
        decision, error = _parse_agent_routing_decision(raw, "fallback", 0.65)
        assert decision.should_trigger is True
        assert decision.task == "open browser"

    def test_agent_route_low_confidence(self):
        import json

        raw = json.dumps(
            {
                "route": "agent",
                "confidence": 0.3,
                "task": "open browser",
                "reason": "uncertain",
            }
        )
        decision, error = _parse_agent_routing_decision(raw, "fallback", 0.65)
        assert decision.should_trigger is False
        # Reason preserves the original when confidence is below threshold
        assert decision.confidence == 0.3

    def test_agent_route_no_task_uses_fallback(self):
        import json

        raw = json.dumps(
            {
                "route": "agent",
                "confidence": 0.9,
                "task": "",
                "reason": "tool needed",
            }
        )
        decision, error = _parse_agent_routing_decision(raw, "fallback task", 0.65)
        assert decision.should_trigger is True
        assert decision.task == "fallback task"

    def test_mutually_exclusive_rejected(self):
        import json

        raw = json.dumps(
            {
                "route": "agent",
                "confidence": 0.9,
                "task": "打开并关闭浏览器",
                "reason": "tool needed",
                "is_atomic": True,
            }
        )
        decision, error = _parse_agent_routing_decision(raw, "fallback", 0.65)
        assert decision.should_trigger is False
        assert decision.is_atomic is False
