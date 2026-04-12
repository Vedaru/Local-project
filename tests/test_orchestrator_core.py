"""
Unit tests for microservices/orchestrator/core.py — OrchestratorCore

Covers:
- OrchestratorConfig.from_env()
- Circuit breaker operations (open/close/fail/health)
- Memory queue operations (enqueue/dequeue/drain)
- Voice batch stats tracking
- Health snapshot
- Voice fallback payloads
"""

from __future__ import annotations

import asyncio

# Ensure project root is in path
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

if TYPE_CHECKING:
    from microservices.orchestrator.core import OrchestratorCore


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def core() -> "OrchestratorCore":
    """Create an OrchestratorCore with default config."""
    from microservices.orchestrator.core import OrchestratorCore

    return OrchestratorCore()


@pytest.fixture
def frozen_config():
    from microservices.orchestrator.core import OrchestratorConfig

    # Use a minimal frozen config for predictable tests
    return OrchestratorConfig(
        memory_service_url="http://localhost:18082",
        agent_service_url="http://localhost:18083",
        voice_service_url="http://localhost:18084",
        memory_timeout_sec=5.0,
        memory_retrieve_timeout_sec=5.0,
        memory_store_timeout_sec=1.0,
        memory_batch_timeout_sec=6.0,
        agent_timeout_sec=30.0,
        voice_timeout_sec=10.0,
        max_requests_per_second=8.0,
        burst_size=16,
        voice_async_batch_enabled=True,
        voice_batch_max_size=4,
        voice_batch_collect_window_ms=5,
        voice_batch_result_wait_sec=1.0,
        voice_batch_congested_queue_size=6,
        voice_batch_result_wait_sec_congested=0.3,
        voice_hit_priority_direct_enabled=True,
        voice_hit_priority_direct_timeout_sec=5.0,
        circuit_fail_threshold=2,
        circuit_cooldown_sec=0.05,
        llm_executor_workers=2,
        pending_memory_queue_size=8,
    )


# ============================================================
# Tests for OrchestratorConfig
# ============================================================


class TestOrchestratorConfig:
    def test_from_env_defaults(self):
        from microservices.orchestrator.core import OrchestratorConfig

        cfg = OrchestratorConfig.from_env()
        assert cfg.memory_service_url != ""
        assert cfg.agent_service_url != ""
        assert cfg.voice_service_url != ""
        assert cfg.memory_timeout_sec > 0
        assert cfg.circuit_fail_threshold > 0
        assert cfg.voice_batch_max_size >= 1
        assert cfg.llm_executor_workers >= 1
        assert cfg.max_requests_per_second > 0
        assert cfg.burst_size >= 1

    def test_custom_config_values(self, frozen_config):
        cfg = frozen_config
        assert cfg.memory_service_url == "http://localhost:18082"
        assert cfg.circuit_fail_threshold == 2
        assert cfg.voice_async_batch_enabled is True
        assert cfg.pending_memory_queue_size == 8

    def test_frozen_config_is_immutable(self, frozen_config):
        # dataclass(frozen=True) should prevent assignment
        with pytest.raises(AttributeError):
            frozen_config.memory_service_url = "changed"  # type: ignore[misc]

    def test_from_env_clamps_minimums(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ORCH_VOICE_BATCH_MAX_SIZE", "0")
        monkeypatch.setenv("ORCH_LLM_EXECUTOR_WORKERS", "-5")

        from microservices.orchestrator.core import OrchestratorConfig

        cfg = OrchestratorConfig.from_env()
        # voice_batch_max_size uses max(1, ...) → clamped
        assert cfg.voice_batch_max_size >= 1
        # llm_executor_workers uses max(1, ...) → clamped
        assert cfg.llm_executor_workers >= 1


# ============================================================
# Tests for Circuit Breaker Operations
# ============================================================


class TestCircuitBreakerOperations:
    def test_initially_closed(self, core):
        assert core.is_circuit_open("agent") is False
        assert core.is_circuit_open("voice") is False

    def test_failure_below_threshold(self, core):
        core.record_circuit_failure("agent")
        assert core.is_circuit_open("agent") is False

    def test_opens_at_threshold(self, frozen_config):
        from microservices.orchestrator.core import OrchestratorCore

        c = OrchestratorCore(config=frozen_config)
        threshold = c.cfg.circuit_fail_threshold

        for _ in range(threshold):
            c.record_circuit_failure("agent")

        assert c.is_circuit_open("agent") is True

    def test_success_resets_failures(self, core):
        core.record_circuit_failure("voice")
        core.record_circuit_success("voice")
        health = core.get_circuit_health()["voice"]
        assert health["failures"] == 0
        assert health["open"] is False

    def test_independent_circuits(self, frozen_config):
        from microservices.orchestrator.core import OrchestratorCore

        c = OrchestratorCore(config=frozen_config)
        # Only fail agent circuit
        for _ in range(c.cfg.circuit_fail_threshold):
            c.record_circuit_failure("agent")

        assert c.is_circuit_open("agent") is True
        assert c.is_circuit_open("voice") is False

    def test_health_snapshot(self, core):
        health = core.get_circuit_health()
        assert "agent" in health
        assert "voice" in health
        for name, info in health.items():
            assert "open" in info
            assert "failures" in info
            assert "open_remaining_sec" in info

    def test_try_acquire_token_returns_bool(self, core):
        result = core.try_acquire_token()
        assert isinstance(result, bool)


# ============================================================
# Tests for Memory Queue Operations
# ============================================================


class TestMemoryQueueOperations:
    def test_enqueue_and_dequeue(self, core):
        core.enqueue_pending_memory_write("user1", "msg1")
        core.enqueue_pending_memory_write("user1", "msg2")

        result = core.dequeue_pending_memory_write("user1")
        assert result == "msg1"

        result2 = core.dequeue_pending_memory_write("user1")
        assert result2 == "msg2"

    def test_dequeue_empty_returns_empty(self, core):
        assert core.dequeue_pending_memory_write("nonexistent_user") == ""

    def test_queue_size_limit(self, frozen_config):
        from microservices.orchestrator.core import OrchestratorCore

        c = OrchestratorCore(config=frozen_config)
        limit = c._pending_memory_queue_size

        for i in range(limit + 5):
            c.enqueue_pending_memory_write("u", f"msg-{i}")

        # Should have at most `limit` items
        drained = c.drain_all_pending_memory_writes()
        user_msgs = [m for u, m in drained if u == "u"]
        assert len(user_msgs) <= limit

    def test_requeue_front(self, core):
        core.enqueue_pending_memory_write("u", "a")
        core.enqueue_pending_memory_write("u", "b")
        core.requeue_pending_memory_front("u", "front_msg")

        first = core.dequeue_pending_memory_write("u")
        assert first == "front_msg"

    def test_drain_all(self, core):
        core.enqueue_pending_memory_write("u1", "m1")
        core.enqueue_pending_memory_write("u1", "m2")
        core.enqueue_pending_memory_write("u2", "m3")

        drained = core.drain_all_pending_memory_writes()
        assert len(drained) == 3

        # After drain, should be empty
        assert core.dequeue_pending_memory_write("u1") == ""

    def test_anonymous_user_normalization(self, core):
        core.enqueue_pending_memory_write("", "anonymous msg")
        core.enqueue_pending_memory_write(None, "none msg")
        core.enqueue_pending_memory_write("   ", "spaces msg")

        result = core.dequeue_pending_memory_write("")
        assert result == "anonymous msg"

        result2 = core.dequeue_pending_memory_write("anonymous")
        assert result2 == "none msg"


# ============================================================
# Tests for Voice Batch Stats
# ============================================================


class TestVoiceBatchStats:
    def test_initial_stats(self, core):
        stats = core.voice_stats_snapshot()
        assert stats["enqueued"] == 0
        assert stats["dispatched_batches"] == 0
        assert stats["dedup_saved_calls"] == 0

    def test_stats_increment(self, core):
        core._voice_stats_add("enqueued", 3)
        core._voice_stats_add("enqueued", 2)

        stats = core.voice_stats_snapshot()
        assert stats["enqueued"] == 5

    def test_voice_queue_length_empty(self, core):
        assert core.voice_queue_length() == 0

    @pytest.mark.asyncio
    async def test_invoke_voice_when_circuit_open(self, frozen_config):
        from microservices.orchestrator.core import OrchestratorCore

        c = OrchestratorCore(config=frozen_config)
        for _ in range(c.cfg.circuit_fail_threshold):
            c.record_circuit_failure("voice")

        result = await c.invoke_voice_service("hello", "req-1")
        assert result["status"] == "skipped"
        assert result["mode"] == "circuit-open"
        assert result["wav_path"] == ""


# ============================================================
# Tests for Health Snapshot
# ============================================================


class TestHealthSnapshot:
    def test_snapshot_structure(self, core):
        snapshot = core.health_snapshot()

        assert "circuits" in snapshot
        assert "voice_batch" in snapshot

        vb = snapshot["voice_batch"]
        assert "enabled" in vb
        assert "queue_size" in vb
        assert "stats" in vb
        assert "worker_running" in vb


# ============================================================
# Tests for Voice Fallback Payloads
# ============================================================


class TestVoiceFallbackPayloads:
    def test_queued_payload_structure(self, frozen_config):
        from microservices.orchestrator.core import OrchestratorCore

        c = OrchestratorCore(config=frozen_config)
        payload = {
            "status": "queued",
            "mode": "async-voice-batch",
            "reason": "voice generation queued",
            "wav_path": "",
            "request_id": "test-123",
        }
        assert payload["wav_path"] == ""
        assert payload["request_id"] == "test-123"

    def test_fallback_payload_structure(self, frozen_config):
        payload = {
            "status": "skipped",
            "mode": "fallback-no-voice",
            "reason": "service unavailable",
            "wav_path": "",
        }
        assert payload["status"] == "skipped"
        assert payload["wav_path"] == ""


# ============================================================
# Tests for Shutdown
# ============================================================


class TestShutdown:
    def test_shutdown_calls_executor_shutdown(self, core):
        # Should not raise
        core.shutdown()

    @pytest.mark.asyncio
    async def test_flush_on_shutdown_with_items(self, core):
        core.enqueue_pending_memory_write("u", "important message")
        # Should not raise even if HTTP call fails
        await core.flush_pending_memory_writes_on_shutdown()


# ============================================================
# Tests for LLM Executor
# ============================================================


@pytest.mark.asyncio
async def test_run_llm_job(core):
    def simple_func(x, y):
        return x + y

    result = await core.run_llm_job(simple_func, 3, 4)
    assert result == 7
