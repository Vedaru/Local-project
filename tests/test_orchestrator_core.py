"""
Tests for microservices/orchestrator/core.py — OrchestratorCore

Covers:
- OrchestratorConfig initialization
- TokenBucket rate limiting
- Circuit breaker state management
- Voice batch queue operations
- Memory queue operations
- Health snapshot
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from microservices.orchestrator.core import (
    CircuitState,
    OrchestratorConfig,
    OrchestratorCore,
    TokenBucket,
    VoiceBatchJob,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_tuning():
    """Provide a mock TuningConfig."""
    tuning = MagicMock()
    o = tuning.orchestrator
    s = tuning.services

    s.memory_service_url = "http://localhost:18082"
    s.agent_service_url = "http://localhost:18083"
    s.voice_service_url = "http://localhost:18084"

    o.memory_timeout_sec = 8.0
    o.memory_retrieve_timeout_sec = 5.0
    o.memory_store_timeout_sec = 5.0
    o.agent_timeout_sec = 180.0
    o.voice_timeout_sec = 60.0
    o.max_requests_per_second = 10.0
    o.burst_size = 10
    o.voice_async_batch_enabled = False
    o.voice_batch_max_size = 5
    o.voice_batch_collect_window_ms = 100
    o.voice_batch_result_wait_sec = 5.0
    o.voice_batch_congested_queue_size = 10
    o.voice_batch_result_wait_sec_congested = 2.0
    o.voice_hit_priority_direct_enabled = False
    o.voice_hit_priority_direct_timeout_sec = 5.0
    o.circuit_fail_threshold = 5
    o.circuit_cooldown_sec = 30.0
    o.llm_executor_workers = 2
    o.pending_memory_queue_size = 100

    return tuning


@pytest.fixture
def config(mock_tuning):
    """Create an OrchestratorConfig from mock tuning."""
    return OrchestratorConfig.from_tuning(mock_tuning)


@pytest.fixture
def core(config):
    """Create an OrchestratorCore instance."""
    return OrchestratorCore(config=config)


# ============================================================
# OrchestratorConfig Tests
# ============================================================


class TestOrchestratorConfig:
    """Test OrchestratorConfig dataclass."""

    def test_from_tuning(self, config):
        assert config.memory_service_url == "http://localhost:18082"
        assert config.agent_service_url == "http://localhost:18083"
        assert config.voice_service_url == "http://localhost:18084"
        assert config.memory_timeout_sec == 8.0
        assert config.agent_timeout_sec == 180.0
        assert config.voice_timeout_sec == 60.0

    def test_computed_batch_timeout(self, config):
        # batch_timeout = max(retrieve, store) + 0.8
        expected = max(5.0, 5.0) + 0.8
        assert config.memory_batch_timeout_sec == expected

    def test_immutable(self, config):
        with pytest.raises(AttributeError):
            config.memory_service_url = "http://other:1234"


# ============================================================
# TokenBucket Tests
# ============================================================


class TestTokenBucket:
    """Test TokenBucket rate limiter."""

    def test_initial_capacity(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        snap = bucket.snapshot()
        assert snap["capacity"] == 5.0
        assert snap["tokens"] == 5.0

    def test_acquire_success(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.try_acquire(1.0) is True

    def test_acquire_exhaustion(self):
        bucket = TokenBucket(capacity=2, refill_rate=0.0)
        assert bucket.try_acquire(1.0) is True
        assert bucket.try_acquire(1.0) is True
        assert bucket.try_acquire(1.0) is False

    def test_refill_over_time(self):
        bucket = TokenBucket(capacity=2, refill_rate=10.0)
        bucket.try_acquire(2.0)  # exhaust
        time.sleep(0.15)  # wait for refill
        assert bucket.try_acquire(1.0) is True

    def test_set_refill_rate(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        bucket.set_refill_rate(10.0)
        snap = bucket.snapshot()
        assert snap["refill_rate"] == 10.0


# ============================================================
# Circuit Breaker Tests
# ============================================================


class TestCircuitBreaker:
    """Test circuit breaker state management."""

    def test_initial_state(self, core):
        assert core.is_circuit_open("agent") is False
        assert core.is_circuit_open("voice") is False

    def test_record_success(self, core):
        core.record_circuit_failure("agent")
        core.record_circuit_success("agent")
        health = core.get_circuit_health()
        assert health["agent"]["failures"] == 0

    def test_circuit_opens_after_threshold(self, core):
        for _ in range(core.cfg.circuit_fail_threshold):
            core.record_circuit_failure("agent")
        assert core.is_circuit_open("agent") is True

    def test_circuit_closes_after_cooldown(self, core):
        for _ in range(core.cfg.circuit_fail_threshold):
            core.record_circuit_failure("agent")

        # Manually expire the circuit
        core._circuits["agent"].opened_until = time.time() - 1
        assert core.is_circuit_open("agent") is False

    def test_health_snapshot(self, core):
        health = core.get_circuit_health()
        assert "agent" in health
        assert "voice" in health
        assert "open" in health["agent"]
        assert "failures" in health["agent"]


# ============================================================
# Memory Queue Tests
# ============================================================


class TestMemoryQueue:
    """Test memory write queue operations."""

    def test_enqueue_and_dequeue(self, core):
        core.enqueue_pending_memory_write("user1", "hello")
        result = core.dequeue_pending_memory_write("user1")
        assert result == "hello"

    def test_dequeue_empty(self, core):
        result = core.dequeue_pending_memory_write("nonexistent")
        assert result == ""

    def test_queue_size_limit(self, core):
        for i in range(core.cfg.pending_memory_queue_size + 10):
            core.enqueue_pending_memory_write("user1", f"msg_{i}")

        # Should not exceed limit
        count = 0
        while True:
            msg = core.dequeue_pending_memory_write("user1")
            if not msg:
                break
            count += 1
        assert count <= core.cfg.pending_memory_queue_size

    def test_drain_all(self, core):
        core.enqueue_pending_memory_write("user1", "msg1")
        core.enqueue_pending_memory_write("user2", "msg2")
        drained = core.drain_all_pending_memory_writes()
        assert len(drained) == 2

    def test_requeue_front(self, core):
        core.enqueue_pending_memory_write("user1", "msg1")
        core.requeue_pending_memory_front("user1", "msg0")
        result = core.dequeue_pending_memory_write("user1")
        assert result == "msg0"


# ============================================================
# Voice Queue Tests
# ============================================================


class TestVoiceQueue:
    """Test voice batch queue operations."""

    def test_initial_queue_length(self, core):
        assert core.voice_queue_length() == 0

    def test_voice_stats(self, core):
        stats = core.voice_stats_snapshot()
        assert "enqueued" in stats
        assert "dequeued" in stats
        assert stats["enqueued"] == 0


# ============================================================
# Health Snapshot Tests
# ============================================================


class TestHealthSnapshot:
    """Test health snapshot generation."""

    def test_snapshot_structure(self, core):
        snapshot = core.health_snapshot()
        assert "circuits" in snapshot
        assert "rate_limiter" in snapshot
        assert "voice_batch" in snapshot

    def test_snapshot_contains_config(self, core):
        snapshot = core.health_snapshot()
        rl = snapshot["rate_limiter"]
        assert rl["max_requests_per_second"] == core.cfg.max_requests_per_second
        assert rl["burst_size"] == core.cfg.burst_size


# ============================================================
# Shutdown Tests
# ============================================================


class TestShutdown:
    """Test shutdown behavior."""

    def test_shutdown_executor(self, core):
        # Should not raise
        core.shutdown()

    def test_flush_empty_memory(self, core):
        # Should not raise on empty queue
        asyncio.run(core.flush_pending_memory_writes_on_shutdown())
