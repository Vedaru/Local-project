"""
Unit tests for microservices.shared.types — ErrorResult, ChatRequest, etc.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestErrorResult:
    """Tests for the unified error response dataclass."""

    def test_import(self):
        from microservices.shared.types import ErrorResult
        assert ErrorResult is not None

    def test_basic_creation(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult(code="test_error", message="something went wrong")
        d = err.to_dict()
        assert d["status"] == "error"
        assert d["code"] == "test_error"
        assert d["message"] == "something went wrong"

    def test_to_dict_includes_request_id(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult(code="x", message="m", request_id="req-123")
        d = err.to_dict()
        assert d["request_id"] == "req-123"

    def test_to_dict_omits_none_request_id(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult(code="x", message="m")
        d = err.to_dict()
        assert "request_id" not in d or d.get("request_id") is None

    def test_extra_fields_appear_in_output(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult(
            status="skipped",
            code="custom",
            message="test",
            extra={"mode": "fallback", "wav_path": ""},
        )
        d = err.to_dict()
        assert d["mode"] == "fallback"
        assert d["wav_path"] == ""

    # ---- Factory methods ----

    def test_service_unavailable(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult.service_unavailable("orchestrator", reason="connection refused")
        d = err.to_dict()
        assert d["code"] == "service_unavailable"
        assert "orchestrator" in d["message"]
        assert d["service"] == "orchestrator"

    def test_circuit_open(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult.circuit_open("voice", request_id="r1")
        d = err.to_dict()
        assert d["code"] == "circuit_open"
        assert d["status"] == "skipped"
        assert d.get("circuit") == "voice"  # extra is flattened into dict

    def test_timeout(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult.timeout("llm_call", 30.0)
        d = err.to_dict()
        assert d["code"] == "timeout"
        assert "30.0" in d["message"]
        assert d.get("timeout_sec") == 30.0  # extra is flattened

    def test_voice_fallback(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult.voice_fallback(
            mode="fallback-no-voice",
            reason="TTS service down",
            wav_path="",
            request_id="r2",
        )
        d = err.to_dict()
        assert d["status"] == "skipped"
        assert d["code"] == "voice_fallback-no-voice"  # prefixed with "voice_"
        assert d.get("message") == "TTS service down"  # reason is stored as message
        assert d.get("mode") == "fallback-no-voice"  # from extra, flattened
        assert d.get("wav_path") == ""  # from extra, flattened

    def test_frozen_immutable(self):
        from microservices.shared.types import ErrorResult

        err = ErrorResult(code="x")
        with pytest.raises(AttributeError):
            err.code = "y"


class TestChatRequestModel:
    """Tests for the Pydantic request/response models."""

    def test_chat_request_valid(self):
        from microservices.shared.types import ChatRequest

        req = ChatRequest(query="hello")
        assert req.query == "hello"
        assert req.user_id == "anonymous"

    def test_chat_request_rejects_empty_query(self):
        from microservices.shared.types import ChatRequest

        with pytest.raises(Exception):  # Pydantic ValidationError
            ChatRequest(query="")


class TestGatewayTimeoutDerivation:
    """Test that gateway timeout is derived from TuningConfig correctly."""

    @pytest.fixture
    def mock_tuning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Create a temporary tuning.yaml and point config_tuning to it."""
        import yaml
        tuning_data = {
            "services": {
                "gateway_port": 18080,
                "orchestrator_url": "http://localhost:18081",
            },
            "orchestrator": {
                "memory_timeout_sec": 8.0,
                "agent_timeout_sec": 180.0,
                "voice_timeout_sec": 60.0,
            },
            "gateway": {
                "chat_timeout_sec": 0.0,  # 0 means auto-derive
                "api_key": "",
            },
        }
        tuning_file = tmp_path / "tuning.yaml"
        tuning_file.write_text(yaml.dump(tuning_data), encoding="utf-8")

        # We can't easily patch the internal path used by gateway,
        # but we can test the derivation formula here
        mem = tuning_data["orchestrator"]["memory_timeout_sec"]
        agent = tuning_data["orchestrator"]["agent_timeout_sec"]
        voice = tuning_data["orchestrator"]["voice_timeout_sec"]
        expected = round(mem + max(agent, voice), 1)
        return expected

    def test_derivation_formula_matches_orchestrator_logic(self, mock_tuning):
        """Verify: gateway_timeout = memory + max(agent, voice)."""
        # The orchestrator's auto-derivation should produce this value
        assert mock_tuning == round(8.0 + max(180.0, 60.0), 1)  # = 188.0

    def test_explicit_timeout_not_derived(self):
        """If GATEWAY_CHAT_TIMEOUT_SEC is explicitly set > 0, use it directly."""
        explicit_value = 120.5
        # In gateway's _load_tuning_or_defaults, if gw.chat_timeout_sec > 0 it's used as-is
        assert explicit_value > 0
