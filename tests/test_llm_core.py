"""
Tests for modules/llm.py — LLM core functions

Covers:
- call_llm success/failure/retry paths
- _handle_llm_retry behavior
- _translate_openai_error mapping
- _build_enhanced_prompt and caching
- _extract_completed_sentences
- call_llm_with_sentence_callback
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from modules.llm import (
    _build_enhanced_prompt,
    _compute_backoff_delay,
    _extract_completed_sentences,
    _get_enhanced_prompt,
    _handle_llm_retry,
    _translate_openai_error,
    call_llm,
    call_llm_with_sentence_callback,
)

# ============================================================
# _translate_openai_error Tests
# ============================================================


class TestTranslateOpenaiError:
    """Test _translate_openai_error mapping."""

    def test_connection_error_maps_to_service_unavailable(self):
        from openai import APIConnectionError

        exc = APIConnectionError(request=MagicMock())
        result = _translate_openai_error(exc)
        assert result.__class__.__name__ == "ServiceUnavailableError"
        assert "llm" in str(result)

    def test_timeout_error_maps_to_service_unavailable(self):
        from openai import APITimeoutError

        exc = APITimeoutError(request=MagicMock())
        result = _translate_openai_error(exc)
        assert result.__class__.__name__ == "ServiceUnavailableError"

    def test_rate_limit_error_maps_to_rate_limit(self):
        from openai import RateLimitError

        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.json.return_value = {"error": {"message": "rate limited"}}
        exc = RateLimitError(
            message="rate limited",
            response=response,
            body={"error": {"message": "rate limited"}},
        )
        result = _translate_openai_error(exc)
        assert result.__class__.__name__ == "RateLimitError"

    def test_status_error_maps_to_service_unavailable(self):
        from openai import APIStatusError

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        response.json.return_value = {"error": {"message": "internal error"}}
        exc = APIStatusError(
            message="internal error",
            response=response,
            body={"error": {"message": "internal error"}},
        )
        result = _translate_openai_error(exc)
        assert result.__class__.__name__ == "ServiceUnavailableError"
        assert "500" in str(result)

    def test_unknown_error_returned_as_is(self):
        exc = ValueError("unknown")
        result = _translate_openai_error(exc)
        assert result is exc


# ============================================================
# _handle_llm_retry Tests
# ============================================================


class TestHandleLlmRetry:
    """Test _handle_llm_retry behavior."""

    @patch("modules.llm.time.sleep")
    def test_rate_limit_retries_when_attempts_remaining(self, mock_sleep):
        from openai import RateLimitError

        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.json.return_value = {"error": {"message": "rate limited"}}
        exc = RateLimitError(
            message="rate limited",
            response=response,
            body={"error": {"message": "rate limited"}},
        )
        result = _handle_llm_retry(exc, attempt=0, max_retries=2, label="Test")
        assert result is True
        mock_sleep.assert_called_once()

    def test_rate_limit_stops_when_no_attempts_remaining(self):
        from openai import RateLimitError

        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.json.return_value = {"error": {"message": "rate limited"}}
        exc = RateLimitError(
            message="rate limited",
            response=response,
            body={"error": {"message": "rate limited"}},
        )
        result = _handle_llm_retry(exc, attempt=2, max_retries=2, label="Test")
        assert result is False

    @patch("modules.llm.time.sleep")
    def test_connection_error_retries(self, mock_sleep):
        from openai import APIConnectionError

        exc = APIConnectionError(request=MagicMock())
        result = _handle_llm_retry(exc, attempt=0, max_retries=2, label="Test")
        assert result is True

    def test_status_error_does_not_retry(self):
        from openai import APIStatusError

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        response.json.return_value = {"error": {"message": "internal error"}}
        exc = APIStatusError(
            message="internal error",
            response=response,
            body={"error": {"message": "internal error"}},
        )
        result = _handle_llm_retry(exc, attempt=0, max_retries=2, label="Test")
        assert result is False


# ============================================================
# _build_enhanced_prompt Tests
# ============================================================


class TestBuildEnhancedPrompt:
    """Test _build_enhanced_prompt and caching."""

    def test_contains_base_prompt(self):
        result = _build_enhanced_prompt("你是助手")
        assert "你是助手" in result

    def test_contains_output_spec(self):
        result = _build_enhanced_prompt("")
        assert "对话输出规范" in result

    def test_contains_agent_trigger_when_not_present(self):
        result = _build_enhanced_prompt("基础提示词")
        assert "SUMMON_AGENT" in result

    def test_no_duplicate_agent_trigger(self):
        result = _build_enhanced_prompt("已有[SUMMON_AGENT]标签")
        # Should only have one occurrence of the trigger instruction
        assert result.count("Agent 触发原则") == 1

    def test_caching_returns_same_result(self):
        _get_enhanced_prompt.cache_clear() if hasattr(_get_enhanced_prompt, "cache_clear") else None
        r1 = _get_enhanced_prompt("test prompt")
        r2 = _get_enhanced_prompt("test prompt")
        assert r1 is r2  # Same object from cache


# ============================================================
# _extract_completed_sentences Tests
# ============================================================


class TestExtractCompletedSentences:
    """Test _extract_completed_sentences."""

    def test_empty_buffer(self):
        completed, remainder = _extract_completed_sentences("")
        assert completed == []
        assert remainder == ""

    def test_no_sentence_delimiter(self):
        completed, remainder = _extract_completed_sentences("hello world")
        assert completed == []
        assert remainder == "hello world"

    def test_chinese_period(self):
        completed, remainder = _extract_completed_sentences("你好。世界。")
        assert completed == ["你好。", "世界。"]
        assert remainder == ""

    def test_mixed_delimiters(self):
        completed, remainder = _extract_completed_sentences("你好！世界？")
        assert completed == ["你好！", "世界？"]

    def test_partial_sentence(self):
        completed, remainder = _extract_completed_sentences("你好。世界")
        assert completed == ["你好。"]
        assert remainder == "世界"

    def test_newline_delimiter(self):
        completed, remainder = _extract_completed_sentences("line1\nline2\n")
        assert completed == ["line1\n", "line2\n"]


# ============================================================
# call_llm Tests
# ============================================================


class TestCallLlm:
    """Test call_llm core function."""

    @patch("modules.llm.client")
    def test_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello, world!"
        mock_client.chat.completions.create.return_value = mock_response

        result = call_llm("system", "model", "hello")
        assert result == "Hello, world!"

    @patch("modules.llm.client")
    def test_empty_response_returns_fallback(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_client.chat.completions.create.return_value = mock_response

        result = call_llm("system", "model", "hello")
        assert "抱歉" in result

    def test_missing_model_returns_error(self):
        result = call_llm("system", "", "hello")
        assert "未配置" in result or "抱歉" in result

    def test_missing_prompt_returns_hint(self):
        result = call_llm("system", "model", "")
        assert "输入" in result

    @patch("modules.llm.client")
    def test_retry_on_rate_limit(self, mock_client):
        from openai import RateLimitError

        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.json.return_value = {"error": {"message": "rate limited"}}
        exc = RateLimitError(
            message="rate limited",
            response=response,
            body={"error": {"message": "rate limited"}},
        )
        mock_client.chat.completions.create.side_effect = [
            exc,
            MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))]),
        ]

        with patch("modules.llm.time.sleep"):
            result = call_llm("system", "model", "hello", max_retries=2)
        assert result == "ok"

    @patch("modules.llm.client")
    def test_connection_error_returns_fallback(self, mock_client):
        from openai import APIConnectionError

        mock_client.chat.completions.create.side_effect = APIConnectionError(request=MagicMock())

        with patch("modules.llm.time.sleep"):
            result = call_llm("system", "model", "hello", max_retries=0)
        assert "连接" in result


# ============================================================
# call_llm_with_sentence_callback Tests
# ============================================================


class TestCallLlmWithSentenceCallback:
    """Test call_llm_with_sentence_callback."""

    @patch("modules.llm.client")
    def test_callback_called_for_sentences(self, mock_client):
        sentences = []

        def on_sentence(s):
            sentences.append(s)

        # Simulate streaming response
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "你好。"

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "世界。"

        mock_client.chat.completions.create.return_value = [chunk1, chunk2]

        result = call_llm_with_sentence_callback("system", "model", "hello", on_sentence=on_sentence)
        assert "你好" in result
        assert len(sentences) >= 1

    @patch("modules.llm.client")
    def test_fallback_to_call_llm_on_no_callback(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "fallback result"
        mock_client.chat.completions.create.return_value = mock_response

        result = call_llm_with_sentence_callback("system", "model", "hello", on_sentence=None)
        assert result == "fallback result"
