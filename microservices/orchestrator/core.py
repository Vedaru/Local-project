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

        # --- LLM executor (thread pool) ---
        self._llm_executor = ThreadPoolExecutor(
            max_workers=self.cfg.llm_executor_workers,
            thread_name_prefix="orchestrator-llm",
        )

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

    async def submit_voice_with_batch_scheduler(self, answer: str, request_id: str) -> dict:
        cfg = self.cfg

        if not cfg.voice_async_batch_enabled:
            return await self.invoke_voice_service(answer, request_id)

        if cfg.voice_hit_priority_direct_enabled and self.voice_queue_length() == 0:
            return await self.invoke_voice_service(
                answer,
                request_id,
                timeout_override=min(cfg.voice_timeout_sec, cfg.voice_hit_priority_direct_timeout_sec),
            )

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
        return await loop.run_in_executor(self._llm_executor, partial(func, *args, **kwargs))

    # ---- Health snapshot ----

    def health_snapshot(self) -> dict[str, Any]:
        circuits = self.get_circuit_health()
        cfg = self.cfg
        return {
            "circuits": circuits,
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
