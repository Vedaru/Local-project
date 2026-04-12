"""
Orchestrator Core — 封装编排器的所有可变状态

将原 orchestrator/main.py 中散落的 ~15 个模块级全局变量封装为类实例，
支持:
- 通过 FastAPI app.state 注入，消除全局状态
- 可测试性：每个测试可以创建独立的 OrchestratorCore 实例
- 线程安全：锁和队列都在实例级别管理
- 配置收敛：从 TuningConfig 读取行为参数，替代散落 os.getenv
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Any, Optional

from modules.config import load_tuning
from microservices.shared import http_client
from microservices.shared.types import ErrorResult


# ============================================================
# 配置常量（从环境变量读取，创建时固定）
# ============================================================


@dataclass(frozen=True)
class OrchestratorConfig:
    """Immutable configuration for the orchestrator."""

    memory_service_url: str
    agent_service_url: str
    voice_service_url: str
    memory_timeout_sec: float
    memory_retrieve_timeout_sec: float
    memory_store_timeout_sec: float
    memory_batch_timeout_sec: float
    agent_timeout_sec: float
    voice_timeout_sec: float
    max_requests_per_second: float
    burst_size: int
    voice_async_batch_enabled: bool
    voice_batch_max_size: int
    voice_batch_collect_window_ms: int
    voice_batch_result_wait_sec: float
    voice_batch_congested_queue_size: int
    voice_batch_result_wait_sec_congested: float
    voice_hit_priority_direct_enabled: bool
    voice_hit_priority_direct_timeout_sec: float
    circuit_fail_threshold: int
    circuit_cooldown_sec: float
    llm_executor_workers: int
    pending_memory_queue_size: int

    @classmethod
    def from_tuning(cls, tuning=None) -> "OrchestratorConfig":
        """从 TuningConfig 构建，替代 from_env。"""
        t = tuning or load_tuning()
        o = t.orchestrator
        s = t.services

        # 自动计算 batch_timeout（取 retrieve + store + 余量）
        computed_batch_timeout = max(o.memory_retrieve_timeout_sec, o.memory_store_timeout_sec) + 0.8

        return cls(
            memory_service_url=s.memory_service_url,
            agent_service_url=s.agent_service_url,
            voice_service_url=s.voice_service_url,
            memory_timeout_sec=o.memory_timeout_sec,
            memory_retrieve_timeout_sec=o.memory_retrieve_timeout_sec,
            memory_store_timeout_sec=o.memory_store_timeout_sec,
            memory_batch_timeout_sec=computed_batch_timeout,
            agent_timeout_sec=o.agent_timeout_sec,
            voice_timeout_sec=o.voice_timeout_sec,
            max_requests_per_second=o.max_requests_per_second,
            burst_size=o.burst_size,
            voice_async_batch_enabled=o.voice_async_batch_enabled,
            voice_batch_max_size=o.voice_batch_max_size,
            voice_batch_collect_window_ms=o.voice_batch_collect_window_ms,
            voice_batch_result_wait_sec=o.voice_batch_result_wait_sec,
            voice_batch_congested_queue_size=o.voice_batch_congested_queue_size,
            voice_batch_result_wait_sec_congested=o.voice_batch_result_wait_sec_congested,
            voice_hit_priority_direct_enabled=o.voice_hit_priority_direct_enabled,
            voice_hit_priority_direct_timeout_sec=o.voice_hit_priority_direct_timeout_sec,
            circuit_fail_threshold=o.circuit_fail_threshold,
            circuit_cooldown_sec=o.circuit_cooldown_sec,
            llm_executor_workers=o.llm_executor_workers,
            pending_memory_queue_size=o.pending_memory_queue_size,
        )

    @classmethod
    def from_env(cls) -> "OrchestratorConfig":
        """向后兼容：仍支持从环境变量直接创建（已废弃，建议使用 from_tuning）。"""
        return cls.from_tuning()


# ============================================================
# 内部数据模型
# ============================================================


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: float = 0.0


@dataclass
class VoiceBatchJob:
    text: str
    request_id: str
    future: asyncio.Future


class TokenBucket:
    """Thread-safe token bucket for request shaping."""

    def __init__(self, capacity: float, refill_rate: float):
        self._capacity = max(1.0, float(capacity))
        self._refill_rate = max(0.05, float(refill_rate))
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @property
    def refill_rate(self) -> float:
        return self._refill_rate

    @property
    def capacity(self) -> float:
        return self._capacity

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        if elapsed <= 0.0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        required = max(0.01, float(tokens))
        with self._lock:
            self._refill(time.monotonic())
            if self._tokens >= required:
                self._tokens -= required
                return True
            return False

    def set_refill_rate(self, refill_rate: float) -> None:
        rate = max(0.05, float(refill_rate))
        with self._lock:
            self._refill(time.monotonic())
            self._refill_rate = rate

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            self._refill(time.monotonic())
            return {
                "tokens": float(self._tokens),
                "capacity": float(self._capacity),
                "refill_rate": float(self._refill_rate),
            }


# ============================================================
# OrchestratorCore — 所有状态的唯一持有者
# ============================================================


class OrchestratorCore:
    """
    Encapsulates all mutable state for the orchestrator microservice.

    Replaces the ~15 module-level global variables with instance attributes,
    making the orchestrator testable and safe for concurrent use.
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.cfg = config or OrchestratorConfig.from_env()

        # --- Circuit breaker state ---
        self._circuits: dict[str, CircuitState] = {
            "agent": CircuitState(),
            "voice": CircuitState(),
        }

        # --- Adaptive token bucket limiter ---
        self._base_refill_rate = max(0.1, float(self.cfg.max_requests_per_second))
        self._token_bucket = TokenBucket(
            capacity=max(1, int(self.cfg.burst_size)),
            refill_rate=self._base_refill_rate,
        )
        self._current_refill_rate = self._base_refill_rate
        self._llm_queue_pressure_threshold = max(2, int(self.cfg.llm_executor_workers * 2))
        self._backpressure_min_refill_rate = max(0.05, self._base_refill_rate * 0.2)

        # --- LLM executor (thread pool) ---
        self._llm_executor = ThreadPoolExecutor(
            max_workers=self.cfg.llm_executor_workers,
            thread_name_prefix="orchestrator-llm",
        )
        self._llm_pending_jobs = 0
        self._llm_pending_lock = threading.Lock()

        # --- Pending memory write queue ---
        self._pending_memory_queue_size = self.cfg.pending_memory_queue_size
        self._pending_memory_lock = threading.Lock()
        self._pending_memory_writes: dict[str, deque[str]] = defaultdict(deque)

        # --- Voice batch queue ---
        self._voice_batch_queue: deque[VoiceBatchJob] = deque()
        self._voice_batch_queue_lock = threading.Lock()
        self._voice_batch_queue_event = asyncio.Event()
        self._voice_batch_worker_task: Optional[asyncio.Task] = None

        # Voice batch statistics
        self._voice_batch_stats_lock = threading.Lock()
        self._voice_batch_stats: dict[str, int] = {
            "enqueued": 0,
            "dequeued": 0,
            "dispatched_batches": 0,
            "dispatched_calls": 0,
            "dedup_saved_calls": 0,
            "queued_timeouts": 0,
            "completed_within_wait": 0,
        }

        # --- Streaming TTS helpers ---
        self._prewarm_cache_lock = threading.Lock()
        self._prewarm_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._opener_stats_lock = threading.Lock()
        self._opener_stats: dict[str, int] = defaultdict(int)
        self._default_openers = ("好的", "我明白了", "明白", "没问题", "可以")

    # ---- Circuit Breaker operations ----

    def is_circuit_open(self, name: str) -> bool:
        state = self._circuits[name]
        return state.opened_until > time.time()

    def record_circuit_success(self, name: str) -> None:
        state = self._circuits[name]
        state.failures = 0
        state.opened_until = 0.0

    def record_circuit_failure(self, name: str) -> None:
        state = self._circuits[name]
        state.failures += 1
        if state.failures >= self.cfg.circuit_fail_threshold:
            state.opened_until = time.time() + self.cfg.circuit_cooldown_sec

    def get_circuit_health(self) -> dict[str, Any]:
        now = time.time()
        result = {}
        for name, state in self._circuits.items():
            result[name] = {
                "open": state.opened_until > now,
                "failures": state.failures,
                "open_remaining_sec": max(0.0, state.opened_until - now),
            }
        return result

    # ---- Memory queue operations ----

    def dequeue_pending_memory_write(self, user_id: str) -> str:
        key = (user_id or "anonymous").strip() or "anonymous"
        with self._pending_memory_lock:
            queue = self._pending_memory_writes.get(key)
            if not queue:
                return ""
            item = queue.popleft()
            if not queue:
                self._pending_memory_writes.pop(key, None)
            return item

    def enqueue_pending_memory_write(self, user_id: str, content: str) -> None:
        key = (user_id or "anonymous").strip() or "anonymous"
        normalized = (content or "").strip()
        if not normalized:
            return
        with self._pending_memory_lock:
            queue = self._pending_memory_writes[key]
            queue.append(normalized)
            while len(queue) > self._pending_memory_queue_size:
                queue.popleft()

    def requeue_pending_memory_front(self, user_id: str, content: str) -> None:
        key = (user_id or "anonymous").strip() or "anonymous"
        normalized = (content or "").strip()
        if not normalized:
            return
        with self._pending_memory_lock:
            queue = self._pending_memory_writes[key]
            while len(queue) >= self._pending_memory_queue_size:
                queue.pop()
            queue.appendleft(normalized)

    def drain_all_pending_memory_writes(self) -> list[tuple[str, str]]:
        with self._pending_memory_lock:
            drained: list[tuple[str, str]] = []
            for user_id, queue in list(self._pending_memory_writes.items()):
                while queue:
                    drained.append((user_id, queue.popleft()))
            self._pending_memory_writes.clear()
            return drained

    # ---- Voice batch queue operations ----

    def voice_queue_length(self) -> int:
        with self._voice_batch_queue_lock:
            return len(self._voice_batch_queue)

    def _voice_stats_add(self, field: str, delta: int = 1) -> None:
        with self._voice_batch_stats_lock:
            self._voice_batch_stats[field] = int(self._voice_batch_stats.get(field, 0)) + int(delta)

    def voice_stats_snapshot(self) -> dict[str, int]:
        with self._voice_batch_stats_lock:
            return {k: int(v) for k, v in self._voice_batch_stats.items()}

    def llm_executor_queue_length(self) -> int:
        queued = 0
        work_queue = getattr(self._llm_executor, "_work_queue", None)
        if work_queue is not None and hasattr(work_queue, "qsize"):
            with contextlib.suppress(Exception):
                queued = max(0, int(work_queue.qsize()))
        with self._llm_pending_lock:
            pending = max(0, int(self._llm_pending_jobs) - int(self.cfg.llm_executor_workers))
        return max(queued, pending)

    def _calculate_backpressure_refill_rate(self) -> float:
        voice_queue = self.voice_queue_length()
        voice_threshold = max(1, int(self.cfg.voice_batch_congested_queue_size))
        voice_pressure = float(voice_queue) / float(voice_threshold)

        llm_queue = self.llm_executor_queue_length()
        llm_pressure = float(llm_queue) / float(max(1, self._llm_queue_pressure_threshold))
        pressure = max(voice_pressure, llm_pressure)

        if pressure <= 1.0:
            target = self._base_refill_rate
        elif pressure <= 1.5:
            target = self._base_refill_rate * 0.75
        elif pressure <= 2.0:
            target = self._base_refill_rate * 0.55
        else:
            target = self._base_refill_rate * 0.35

        return max(self._backpressure_min_refill_rate, float(target))

    def try_acquire_token(self) -> bool:
        """Acquire one request token with adaptive refill-rate backpressure."""
        self._current_refill_rate = self._calculate_backpressure_refill_rate()
        self._token_bucket.set_refill_rate(self._current_refill_rate)
        return self._token_bucket.try_acquire(1.0)

    def estimate_retry_after_sec(self) -> float:
        rate = max(0.05, float(self._current_refill_rate))
        return min(2.0, 1.0 / rate)

    # ---- Voice service invocation ----

    async def invoke_voice_service(
        self, text: str, request_id: str, timeout_override: Optional[float] = None
    ) -> dict:
        if self.is_circuit_open("voice"):
            return ErrorResult.voice_fallback(
                mode="circuit-open",
                reason="voice circuit open",
                request_id=request_id,
            ).to_dict()

        try:
            timeout_sec = (
                float(timeout_override)
                if timeout_override is not None
                else self.cfg.voice_timeout_sec
            )
            tts = await http_client.post_json(
                f"{self.cfg.voice_service_url}/speak",
                payload={"text": text, "voice": "default"},
                timeout=max(0.1, timeout_sec),
                headers={"x-request-id": request_id},
            )
            self.record_circuit_success("voice")
            return tts
        except Exception:
            self.record_circuit_failure("voice")
            return ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="voice service unavailable",
                request_id=request_id,
            ).to_dict()

    # ---- Voice batch dispatch ----

    async def dispatch_voice_batch(self, jobs: list[VoiceBatchJob]) -> None:
        if not jobs:
            return

        grouped: dict[str, list[VoiceBatchJob]] = {}
        for job in jobs:
            grouped.setdefault(job.text, []).append(job)

        unique_jobs = [group[0] for group in grouped.values()]
        dedup_saved = max(0, len(jobs) - len(unique_jobs))

        self._voice_stats_add("dispatched_batches", 1)
        self._voice_stats_add("dispatched_calls", len(unique_jobs))
        if dedup_saved > 0:
            self._voice_stats_add("dedup_saved_calls", dedup_saved)

        results = await asyncio.gather(
            *[self.invoke_voice_service(job.text, job.request_id) for job in unique_jobs],
            return_exceptions=True,
        )

        result_by_text: dict[str, dict] = {}
        for job, result in zip(unique_jobs, results):
            if isinstance(result, Exception):
                result_by_text[job.text] = ErrorResult.voice_fallback(
                    mode="fallback-no-voice",
                    reason="voice batch dispatch failed",
                    request_id=job.request_id,
                ).to_dict()
            else:
                result_by_text[job.text] = result

        for text, grouped_jobs in grouped.items():
            payload = result_by_text.get(text, ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="voice batch dispatch failed",
            ).to_dict())
            for job in grouped_jobs:
                if not job.future.done():
                    job.future.set_result(payload)

    # ---- Voice batch worker lifecycle ----

    async def voice_batch_worker(self) -> None:
        try:
            while True:
                await self._voice_batch_queue_event.wait()
                await asyncio.sleep(self.cfg.voice_batch_collect_window_ms / 1000.0)

                while True:
                    batch: list[VoiceBatchJob] = []
                    with self._voice_batch_queue_lock:
                        while self._voice_batch_queue and len(batch) < self.cfg.voice_batch_max_size:
                            batch.append(self._voice_batch_queue.popleft())
                        if not self._voice_batch_queue:
                            self._voice_batch_queue_event.clear()

                    if not batch:
                        break

                    self._voice_stats_add("dequeued", len(batch))
                    await self.dispatch_voice_batch(batch)
        except asyncio.CancelledError:
            pass
        finally:
            with self._voice_batch_queue_lock:
                pending_jobs = list(self._voice_batch_queue)
                self._voice_batch_queue.clear()
                self._voice_batch_queue_event.clear()

            fallback = ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="voice batch worker stopped",
            ).to_dict()
            for job in pending_jobs:
                if not job.future.done():
                    job.future.set_result(fallback)

    def ensure_voice_batch_worker_started(self) -> None:
        task = self._voice_batch_worker_task
        if task is None or task.done():
            self._voice_batch_worker_task = asyncio.create_task(
                self.voice_batch_worker(), name="orchestrator-voice-batch"
            )

    async def shutdown_voice_batch_worker(self) -> None:
        task = self._voice_batch_worker_task
        self._voice_batch_worker_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # ---- Voice submission with batch scheduling ----

    def _normalize_voice_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def split_text_for_voice_streaming(self, text: str) -> list[str]:
        """Split long answer into speech-friendly chunks by punctuation and length."""
        normalized = self._normalize_voice_text(text)
        if not normalized:
            return []

        hard_breaks = set("。！？!?；;…\n")
        soft_breaks = set("，,、：:")
        max_segment_chars = 42
        min_segment_chars = 6

        segments: list[str] = []
        buffer: list[str] = []

        for ch in normalized:
            buffer.append(ch)
            current = "".join(buffer).strip()
            if not current:
                continue
            should_flush = (
                ch in hard_breaks
                or (ch in soft_breaks and len(current) >= min_segment_chars)
                or len(current) >= max_segment_chars
            )
            if should_flush:
                segments.append(current)
                buffer.clear()

        if buffer:
            segments.append("".join(buffer).strip())

        merged: list[str] = []
        for seg in segments:
            if not seg:
                continue
            if merged and len(seg) < min_segment_chars:
                merged[-1] = (merged[-1] + seg).strip()
                continue
            merged.append(seg)

        return merged or [normalized]

    def _extract_opening_phrase(self, answer: str) -> str:
        normalized = self._normalize_voice_text(answer)
        if not normalized:
            return ""
        match = re.match(r"^(.{1,8}?)([，,。！？!?；;]|\s|$)", normalized)
        phrase = (match.group(1) if match else normalized[:8]).strip()
        return phrase

    def note_answer_opening(self, answer: str) -> None:
        opener = self._extract_opening_phrase(answer)
        if not opener:
            return
        with self._opener_stats_lock:
            self._opener_stats[opener] = int(self._opener_stats.get(opener, 0)) + 1

    def _predict_opening_phrases(self, limit: int = 2) -> list[str]:
        cap = max(1, int(limit))
        with self._opener_stats_lock:
            ranked = sorted(self._opener_stats.items(), key=lambda item: item[1], reverse=True)
        predicted = [text for text, _ in ranked[:cap] if text]
        for default_phrase in self._default_openers:
            if len(predicted) >= cap:
                break
            if default_phrase not in predicted:
                predicted.append(default_phrase)
        return predicted[:cap]

    def _get_prewarmed_voice(self, text: str) -> Optional[dict[str, Any]]:
        key = self._normalize_voice_text(text)
        if not key:
            return None
        now = time.monotonic()
        with self._prewarm_cache_lock:
            cached = self._prewarm_cache.get(key)
            if not cached:
                return None
            created_at, payload = cached
            if now - float(created_at) > 180.0:
                self._prewarm_cache.pop(key, None)
                return None
            result = dict(payload)
            result["prewarmed"] = True
            return result

    def _store_prewarmed_voice(self, text: str, payload: dict[str, Any]) -> None:
        key = self._normalize_voice_text(text)
        wav_path = str(payload.get("wav_path") or "").strip()
        if not key or not wav_path:
            return
        with self._prewarm_cache_lock:
            self._prewarm_cache[key] = (time.monotonic(), dict(payload))

    async def prewarm_voice_openers(self, request_id: str) -> None:
        """Preload likely opening phrases to reduce first-chunk TTS latency."""
        phrases = self._predict_opening_phrases(limit=2)
        if not phrases:
            return

        pending_phrases: list[str] = []
        jobs = []
        for phrase in phrases:
            if self._get_prewarmed_voice(phrase) is not None:
                continue
            pending_phrases.append(phrase)
            jobs.append(self.invoke_voice_service(phrase, request_id))

        if not jobs:
            return

        results = await asyncio.gather(*jobs, return_exceptions=True)
        for phrase, result in zip(pending_phrases, results):
            if isinstance(result, dict):
                self._store_prewarmed_voice(phrase, result)

    async def _submit_single_voice_with_batch_scheduler(self, text: str, request_id: str) -> dict:
        cfg = self.cfg
        answer = self._normalize_voice_text(text)
        if not answer:
            return ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="empty voice text",
                request_id=request_id,
            ).to_dict()

        prewarmed = self._get_prewarmed_voice(answer)
        if prewarmed is not None:
            return prewarmed

        if not cfg.voice_async_batch_enabled:
            result = await self.invoke_voice_service(answer, request_id)
            self._store_prewarmed_voice(answer, result)
            return result

        if cfg.voice_hit_priority_direct_enabled and self.voice_queue_length() == 0:
            result = await self.invoke_voice_service(
                answer,
                request_id,
                timeout_override=min(cfg.voice_timeout_sec, cfg.voice_hit_priority_direct_timeout_sec),
            )
            self._store_prewarmed_voice(answer, result)
            return result

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        with self._voice_batch_queue_lock:
            self._voice_batch_queue.append(
                VoiceBatchJob(text=answer, request_id=request_id, future=future)
            )
            queued_size = len(self._voice_batch_queue)
            self._voice_batch_queue_event.set()

        self._voice_stats_add("enqueued", 1)
        self.ensure_voice_batch_worker_started()

        wait_timeout = cfg.voice_batch_result_wait_sec
        if queued_size >= cfg.voice_batch_congested_queue_size:
            wait_timeout = min(wait_timeout, cfg.voice_batch_result_wait_sec_congested)

        if wait_timeout <= 1e-6:
            self._voice_stats_add("queued_timeouts", 1)
            return {**ErrorResult.voice_fallback(
                mode="async-voice-batch",
                reason="voice generation queued",
                request_id=request_id,
            ).to_dict(), "status": "queued"}

        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=wait_timeout)
            self._voice_stats_add("completed_within_wait", 1)
            self._store_prewarmed_voice(answer, result)
            return result
        except asyncio.TimeoutError:
            self._voice_stats_add("queued_timeouts", 1)
            return {**ErrorResult.voice_fallback(
                mode="async-voice-batch",
                reason="voice generation queued",
                request_id=request_id,
            ).to_dict(), "status": "queued"}
        except Exception:
            return ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="voice batch scheduler error",
                request_id=request_id,
            ).to_dict()

    def merge_voice_segments(self, answer: str, segment_payloads: list[dict[str, Any]], request_id: str) -> dict:
        if not segment_payloads:
            return ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="no voice segment generated",
                request_id=request_id,
            ).to_dict()

        primary = dict(segment_payloads[0])
        merged = {
            **primary,
            "text": self._normalize_voice_text(answer),
            "segments": segment_payloads,
            "segment_count": len(segment_payloads),
            "seamless_concat": len(segment_payloads) > 1,
        }
        return merged

    async def submit_voice_with_batch_scheduler(self, answer: str, request_id: str) -> dict:
        normalized = self._normalize_voice_text(answer)
        if not normalized:
            return ErrorResult.voice_fallback(
                mode="fallback-no-voice",
                reason="empty answer",
                request_id=request_id,
            ).to_dict()

        self.note_answer_opening(normalized)
        segments = self.split_text_for_voice_streaming(normalized)
        if not segments:
            segments = [normalized]

        # 先发送第一段，满足首句优先触发。
        first_segment = segments[0]
        first_payload = await self._submit_single_voice_with_batch_scheduler(first_segment, request_id)
        segment_payloads: list[dict[str, Any]] = [{
            "index": 0,
            "text": first_segment,
            **first_payload,
        }]

        if len(segments) > 1:
            tail_results = await asyncio.gather(
                *[
                    self._submit_single_voice_with_batch_scheduler(segment_text, request_id)
                    for segment_text in segments[1:]
                ],
                return_exceptions=True,
            )
            for idx, (segment_text, result) in enumerate(zip(segments[1:], tail_results), start=1):
                if isinstance(result, dict):
                    segment_payloads.append({
                        "index": idx,
                        "text": segment_text,
                        **result,
                    })
                else:
                    segment_payloads.append({
                        "index": idx,
                        "text": segment_text,
                        **ErrorResult.voice_fallback(
                            mode="fallback-no-voice",
                            reason="voice segment dispatch failed",
                            request_id=request_id,
                        ).to_dict(),
                    })

        return self.merge_voice_segments(normalized, segment_payloads, request_id)

    # ---- Memory flush on shutdown ----

    async def flush_pending_memory_writes_on_shutdown(self) -> None:
        pending_items = self.drain_all_pending_memory_writes()
        if not pending_items:
            return

        for user_id, content in pending_items:
            try:
                await http_client.post_json(
                    f"{self.cfg.memory_service_url}/batch",
                    payload={
                        "query": "",
                        "user_id": user_id,
                        "n_results": 1,
                        "retrieve": False,
                        "store_content": content,
                    },
                    timeout=max(1.0, self.cfg.memory_store_timeout_sec),
                    headers={"x-request-id": "orchestrator-shutdown-flush"},
                )
            except Exception:
                pass

    # ---- LLM execution ----

    async def run_llm_job(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        with self._llm_pending_lock:
            self._llm_pending_jobs += 1
        try:
            return await loop.run_in_executor(self._llm_executor, partial(func, *args, **kwargs))
        finally:
            with self._llm_pending_lock:
                self._llm_pending_jobs = max(0, self._llm_pending_jobs - 1)

    # ---- Health snapshot ----

    def health_snapshot(self) -> dict[str, Any]:
        circuits = self.get_circuit_health()
        cfg = self.cfg
        limiter_snapshot = self._token_bucket.snapshot()
        return {
            "circuits": circuits,
            "rate_limiter": {
                "max_requests_per_second": cfg.max_requests_per_second,
                "burst_size": cfg.burst_size,
                "adaptive_refill_rate": self._current_refill_rate,
                "tokens": limiter_snapshot.get("tokens", 0.0),
                "capacity": limiter_snapshot.get("capacity", float(cfg.burst_size)),
                "llm_queue_size": self.llm_executor_queue_length(),
                "voice_queue_size": self.voice_queue_length(),
            },
            "voice_batch": {
                "enabled": cfg.voice_async_batch_enabled,
                "hit_priority_direct_enabled": cfg.voice_hit_priority_direct_enabled,
                "hit_priority_direct_timeout_sec": cfg.voice_hit_priority_direct_timeout_sec,
                "wait_timeout_sec": cfg.voice_batch_result_wait_sec,
                "wait_timeout_sec_congested": cfg.voice_batch_result_wait_sec_congested,
                "queue_size": self.voice_queue_length(),
                "worker_running": bool(
                    self._voice_batch_worker_task and not self._voice_batch_worker_task.done()
                ),
                "stats": self.voice_stats_snapshot(),
            },
        }

    # ---- Shutdown ----

    def shutdown(self):
        """Shutdown executor resources."""
        self._llm_executor.shutdown(wait=False)
