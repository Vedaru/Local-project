import asyncio
import contextlib
import os
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from modules.config import load_config
from modules.llm import call_llm, decide_agent_routing
from microservices.shared.http_client import close_http_clients, post_json

app = FastAPI(title="project-local-orchestrator", version="0.1.0")

MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:18082")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://localhost:18083")
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://localhost:18084")

MEMORY_TIMEOUT_SEC = float(os.getenv("ORCH_MEMORY_TIMEOUT_SEC", "8"))
MEMORY_RETRIEVE_TIMEOUT_SEC = float(
    os.getenv("ORCH_MEMORY_RETRIEVE_TIMEOUT_SEC", str(MEMORY_TIMEOUT_SEC))
)
MEMORY_STORE_TIMEOUT_SEC = float(os.getenv("ORCH_MEMORY_STORE_TIMEOUT_SEC", "1.8"))
MEMORY_BATCH_TIMEOUT_SEC = float(
    os.getenv(
        "ORCH_MEMORY_BATCH_TIMEOUT_SEC",
        str(max(MEMORY_RETRIEVE_TIMEOUT_SEC, MEMORY_STORE_TIMEOUT_SEC) + 0.8),
    )
)
AGENT_TIMEOUT_SEC = float(os.getenv("ORCH_AGENT_TIMEOUT_SEC", "180"))
VOICE_TIMEOUT_SEC = float(os.getenv("ORCH_VOICE_TIMEOUT_SEC", "60"))
VOICE_ASYNC_BATCH_ENABLED = (
    (os.getenv("ORCH_VOICE_ASYNC_BATCH_ENABLED", "1") or "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
VOICE_BATCH_MAX_SIZE = max(1, int(os.getenv("ORCH_VOICE_BATCH_MAX_SIZE", "8")))
VOICE_BATCH_COLLECT_WINDOW_MS = max(1, int(os.getenv("ORCH_VOICE_BATCH_COLLECT_WINDOW_MS", "8")))
VOICE_BATCH_RESULT_WAIT_SEC = max(0.05, float(os.getenv("ORCH_VOICE_BATCH_RESULT_WAIT_SEC", "1.2")))
VOICE_BATCH_CONGESTED_QUEUE_SIZE = max(1, int(os.getenv("ORCH_VOICE_BATCH_CONGESTED_QUEUE_SIZE", "12")))
VOICE_BATCH_RESULT_WAIT_SEC_CONGESTED = max(
    0.0,
    float(os.getenv("ORCH_VOICE_BATCH_RESULT_WAIT_SEC_CONGESTED", "0.4")),
)
VOICE_HIT_PRIORITY_DIRECT_ENABLED = (
    (os.getenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_ENABLED", "1") or "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC = max(
    0.1,
    float(os.getenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC", "8.0")),
)

CIRCUIT_FAIL_THRESHOLD = int(os.getenv("ORCH_CIRCUIT_FAIL_THRESHOLD", "3"))
CIRCUIT_COOLDOWN_SEC = float(os.getenv("ORCH_CIRCUIT_COOLDOWN_SEC", "30"))


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: float = 0.0


@dataclass
class VoiceBatchJob:
    text: str
    request_id: str
    future: asyncio.Future


_CIRCUITS = {
    "agent": CircuitState(),
    "voice": CircuitState(),
}
_LLM_EXECUTOR_WORKERS = max(1, int(os.getenv("ORCH_LLM_EXECUTOR_WORKERS", "4")))
_LLM_EXECUTOR = ThreadPoolExecutor(
    max_workers=_LLM_EXECUTOR_WORKERS,
    thread_name_prefix="orchestrator-llm",
)
_PENDING_MEMORY_QUEUE_SIZE = max(1, int(os.getenv("ORCH_MEMORY_PENDING_QUEUE_SIZE", "24")))
_PENDING_MEMORY_LOCK = threading.Lock()
_PENDING_MEMORY_WRITES: dict[str, deque[str]] = defaultdict(deque)
_VOICE_BATCH_QUEUE: deque[VoiceBatchJob] = deque()
_VOICE_BATCH_QUEUE_LOCK = threading.Lock()
_VOICE_BATCH_QUEUE_EVENT = asyncio.Event()
_VOICE_BATCH_WORKER_TASK: Optional[asyncio.Task] = None
_VOICE_BATCH_STATS_LOCK = threading.Lock()
_VOICE_BATCH_STATS = {
    "enqueued": 0,
    "dequeued": 0,
    "dispatched_batches": 0,
    "dispatched_calls": 0,
    "dedup_saved_calls": 0,
    "queued_timeouts": 0,
    "completed_within_wait": 0,
}


async def _run_llm_job(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_LLM_EXECUTOR, partial(func, *args, **kwargs))


def _is_open(name: str) -> bool:
    state = _CIRCUITS[name]
    return state.opened_until > time.time()


def _record_success(name: str) -> None:
    state = _CIRCUITS[name]
    state.failures = 0
    state.opened_until = 0.0


def _record_failure(name: str) -> None:
    state = _CIRCUITS[name]
    state.failures += 1
    if state.failures >= CIRCUIT_FAIL_THRESHOLD:
        state.opened_until = time.time() + CIRCUIT_COOLDOWN_SEC


def _request_headers(request_id: str) -> dict:
    return {"x-request-id": request_id}


def _voice_queue_length() -> int:
    with _VOICE_BATCH_QUEUE_LOCK:
        return len(_VOICE_BATCH_QUEUE)


def _voice_stats_add(field: str, delta: int = 1) -> None:
    with _VOICE_BATCH_STATS_LOCK:
        _VOICE_BATCH_STATS[field] = int(_VOICE_BATCH_STATS.get(field, 0)) + int(delta)


def _voice_stats_snapshot() -> dict:
    with _VOICE_BATCH_STATS_LOCK:
        return {k: int(v) for k, v in _VOICE_BATCH_STATS.items()}


def _voice_queued_payload(request_id: str) -> dict:
    return {
        "status": "queued",
        "mode": "async-voice-batch",
        "reason": "voice generation queued",
        "wav_path": "",
        "request_id": request_id,
    }


def _voice_fallback_payload(reason: str) -> dict:
    return {
        "status": "skipped",
        "mode": "fallback-no-voice",
        "reason": reason,
        "wav_path": "",
    }


async def _invoke_voice_service(text: str, request_id: str, timeout_override: Optional[float] = None) -> dict:
    if _is_open("voice"):
        return {
            "status": "skipped",
            "mode": "circuit-open",
            "reason": "voice circuit open",
            "wav_path": "",
        }

    try:
        timeout_sec = float(timeout_override) if timeout_override is not None else VOICE_TIMEOUT_SEC
        tts = await post_json(
            f"{VOICE_SERVICE_URL}/speak",
            payload={"text": text, "voice": "default"},
            timeout=max(0.1, timeout_sec),
            headers=_request_headers(request_id),
        )
        _record_success("voice")
        return tts
    except Exception:
        _record_failure("voice")
        return _voice_fallback_payload("voice service unavailable")


async def _dispatch_voice_batch(jobs: list[VoiceBatchJob]) -> None:
    if not jobs:
        return

    grouped: dict[str, list[VoiceBatchJob]] = {}
    for job in jobs:
        grouped.setdefault(job.text, []).append(job)

    unique_jobs = [group[0] for group in grouped.values()]
    dedup_saved = max(0, len(jobs) - len(unique_jobs))

    _voice_stats_add("dispatched_batches", 1)
    _voice_stats_add("dispatched_calls", len(unique_jobs))
    if dedup_saved > 0:
        _voice_stats_add("dedup_saved_calls", dedup_saved)

    results = await asyncio.gather(
        *[_invoke_voice_service(job.text, job.request_id) for job in unique_jobs],
        return_exceptions=True,
    )

    result_by_text: dict[str, dict] = {}
    for job, result in zip(unique_jobs, results):
        if isinstance(result, Exception):
            result_by_text[job.text] = _voice_fallback_payload("voice batch dispatch failed")
        else:
            result_by_text[job.text] = result

    for text, grouped_jobs in grouped.items():
        payload = result_by_text.get(text, _voice_fallback_payload("voice batch dispatch failed"))
        for job in grouped_jobs:
            if not job.future.done():
                job.future.set_result(payload)


async def _voice_batch_worker() -> None:
    try:
        while True:
            await _VOICE_BATCH_QUEUE_EVENT.wait()
            await asyncio.sleep(VOICE_BATCH_COLLECT_WINDOW_MS / 1000.0)

            while True:
                batch: list[VoiceBatchJob] = []
                with _VOICE_BATCH_QUEUE_LOCK:
                    while _VOICE_BATCH_QUEUE and len(batch) < VOICE_BATCH_MAX_SIZE:
                        batch.append(_VOICE_BATCH_QUEUE.popleft())
                    if not _VOICE_BATCH_QUEUE:
                        _VOICE_BATCH_QUEUE_EVENT.clear()

                if not batch:
                    break

                _voice_stats_add("dequeued", len(batch))

                await _dispatch_voice_batch(batch)
    except asyncio.CancelledError:
        pass
    finally:
        with _VOICE_BATCH_QUEUE_LOCK:
            pending_jobs = list(_VOICE_BATCH_QUEUE)
            _VOICE_BATCH_QUEUE.clear()
            _VOICE_BATCH_QUEUE_EVENT.clear()

        for job in pending_jobs:
            if not job.future.done():
                job.future.set_result(_voice_fallback_payload("voice batch worker stopped"))


def _ensure_voice_batch_worker_started() -> None:
    global _VOICE_BATCH_WORKER_TASK
    task = _VOICE_BATCH_WORKER_TASK
    if task is None or task.done():
        _VOICE_BATCH_WORKER_TASK = asyncio.create_task(_voice_batch_worker(), name="orchestrator-voice-batch")


async def _shutdown_voice_batch_worker() -> None:
    global _VOICE_BATCH_WORKER_TASK
    task = _VOICE_BATCH_WORKER_TASK
    _VOICE_BATCH_WORKER_TASK = None
    if task is None:
        return

    if not task.done():
        task.cancel()

    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def _submit_voice_with_batch_scheduler(answer: str, request_id: str) -> dict:
    if not VOICE_ASYNC_BATCH_ENABLED:
        return await _invoke_voice_service(answer, request_id)

    if VOICE_HIT_PRIORITY_DIRECT_ENABLED and _voice_queue_length() == 0:
        return await _invoke_voice_service(
            answer,
            request_id,
            timeout_override=min(VOICE_TIMEOUT_SEC, VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC),
        )

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    with _VOICE_BATCH_QUEUE_LOCK:
        _VOICE_BATCH_QUEUE.append(
            VoiceBatchJob(
                text=answer,
                request_id=request_id,
                future=future,
            )
        )
        queued_size = len(_VOICE_BATCH_QUEUE)
        _VOICE_BATCH_QUEUE_EVENT.set()

    _voice_stats_add("enqueued", 1)

    _ensure_voice_batch_worker_started()

    wait_timeout = VOICE_BATCH_RESULT_WAIT_SEC
    if queued_size >= VOICE_BATCH_CONGESTED_QUEUE_SIZE:
        wait_timeout = min(wait_timeout, VOICE_BATCH_RESULT_WAIT_SEC_CONGESTED)

    if wait_timeout <= 1e-6:
        _voice_stats_add("queued_timeouts", 1)
        return _voice_queued_payload(request_id)

    try:
        result = await asyncio.wait_for(asyncio.shield(future), timeout=wait_timeout)
        _voice_stats_add("completed_within_wait", 1)
        return result
    except asyncio.TimeoutError:
        _voice_stats_add("queued_timeouts", 1)
        return _voice_queued_payload(request_id)
    except Exception:
        return _voice_fallback_payload("voice batch scheduler error")


def _dequeue_pending_memory_write(user_id: str) -> str:
    key = (user_id or "anonymous").strip() or "anonymous"
    with _PENDING_MEMORY_LOCK:
        queue = _PENDING_MEMORY_WRITES.get(key)
        if not queue:
            return ""

        item = queue.popleft()
        if not queue:
            _PENDING_MEMORY_WRITES.pop(key, None)
        return item


def _enqueue_pending_memory_write(user_id: str, content: str) -> None:
    key = (user_id or "anonymous").strip() or "anonymous"
    normalized = (content or "").strip()
    if not normalized:
        return

    with _PENDING_MEMORY_LOCK:
        queue = _PENDING_MEMORY_WRITES[key]
        queue.append(normalized)
        while len(queue) > _PENDING_MEMORY_QUEUE_SIZE:
            queue.popleft()


def _requeue_pending_memory_front(user_id: str, content: str) -> None:
    key = (user_id or "anonymous").strip() or "anonymous"
    normalized = (content or "").strip()
    if not normalized:
        return

    with _PENDING_MEMORY_LOCK:
        queue = _PENDING_MEMORY_WRITES[key]
        while len(queue) >= _PENDING_MEMORY_QUEUE_SIZE:
            queue.pop()
        queue.appendleft(normalized)


def _drain_all_pending_memory_writes() -> list[tuple[str, str]]:
    with _PENDING_MEMORY_LOCK:
        drained: list[tuple[str, str]] = []
        for user_id, queue in list(_PENDING_MEMORY_WRITES.items()):
            while queue:
                drained.append((user_id, queue.popleft()))
        _PENDING_MEMORY_WRITES.clear()
        return drained


async def _flush_pending_memory_writes_on_shutdown() -> None:
    pending_items = _drain_all_pending_memory_writes()
    if not pending_items:
        return

    for user_id, content in pending_items:
        try:
            await post_json(
                f"{MEMORY_SERVICE_URL}/batch",
                payload={
                    "query": "",
                    "user_id": user_id,
                    "n_results": 1,
                    "retrieve": False,
                    "store_content": content,
                },
                timeout=max(1.0, MEMORY_STORE_TIMEOUT_SEC),
                headers={"x-request-id": "orchestrator-shutdown-flush"},
            )
        except Exception:
            # 进程退出阶段失败时不再重试。
            pass


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    route_to_agent: bool = Field(default=False)
    force_chat_only: bool = Field(default=False)


@app.get("/health")
async def health() -> dict:
    now = time.time()
    return {
        "status": "ok",
        "service": "orchestrator",
        "circuits": {
            "agent": {
                "open": _is_open("agent"),
                "failures": _CIRCUITS["agent"].failures,
                "open_remaining_sec": max(0.0, _CIRCUITS["agent"].opened_until - now),
            },
            "voice": {
                "open": _is_open("voice"),
                "failures": _CIRCUITS["voice"].failures,
                "open_remaining_sec": max(0.0, _CIRCUITS["voice"].opened_until - now),
            },
        },
        "voice_batch": {
            "enabled": VOICE_ASYNC_BATCH_ENABLED,
            "hit_priority_direct_enabled": VOICE_HIT_PRIORITY_DIRECT_ENABLED,
            "hit_priority_direct_timeout_sec": VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC,
            "wait_timeout_sec": VOICE_BATCH_RESULT_WAIT_SEC,
            "wait_timeout_sec_congested": VOICE_BATCH_RESULT_WAIT_SEC_CONGESTED,
            "queue_size": _voice_queue_length(),
            "worker_running": bool(_VOICE_BATCH_WORKER_TASK and not _VOICE_BATCH_WORKER_TASK.done()),
            "stats": _voice_stats_snapshot(),
        },
    }


@app.on_event("shutdown")
async def shutdown_event() -> None:
    _LLM_EXECUTOR.shutdown(wait=False)
    await _flush_pending_memory_writes_on_shutdown()
    await _shutdown_voice_batch_worker()
    await close_http_clients()


@app.post("/chat")
async def chat(request: ChatRequest, http_request: Request) -> dict:
    """
    高度并行的 Chat 流水线：

    Phase 1（并行）: Memory 检索+存储  +  LLM 路由决策
    Phase 2（串行） : 根据路由结果调用 Agent 或 LLM 生成回答
    Phase 3（并行）: TTS 语音合成       +  Memory 延迟写入入队
    """
    try:
        request_id = http_request.headers.get("x-request-id", "")
        pending_store_content = _dequeue_pending_memory_write(request.user_id)

        cfg = load_config()
        system_prompt = cfg.system_prompt or ""
        model_name = cfg.model_name or ""

        # ══════════════════════════════════════════════════════════
        # Phase 1 — 并行启动: Memory 批处理 + 路由决策
        # ══════════════════════════════════════════════════════════
        routed_to_agent = bool(request.route_to_agent)
        route_reason = "forced_by_request" if routed_to_agent else ""

        async def _fetch_memory():
            """Memory 检索+存储任务。"""
            nonlocal memory_text, memory_retrieve_status, memory_store_flush_status
            memory_text = ""
            memory_retrieve_status = "ok"
            memory_store_flush_status = "skipped"
            try:
                payload = {
                    "query": request.query,
                    "user_id": request.user_id,
                    "n_results": 4,
                    "retrieve": True,
                    "store_content": pending_store_content or "",
                }
                ctx = await post_json(
                    f"{MEMORY_SERVICE_URL}/batch",
                    payload=payload,
                    timeout=MEMORY_BATCH_TIMEOUT_SEC,
                    headers=_request_headers(request_id),
                )
                memory_text = ctx.get("context", "")
                rs = str(ctx.get("retrieve_status", "")).strip().lower()
                if rs == "failed":
                    memory_retrieve_status = "fallback-empty"
                elif rs == "empty":
                    pass  # 空结果不算失败
                if pending_store_content:
                    ss = str(ctx.get("store_status", "")).strip().lower()
                    if ss == "stored":
                        memory_store_flush_status = "ok"
                    else:
                        memory_store_flush_status = "failed"
                        _requeue_pending_memory_front(request.user_id, pending_store_content)
            except Exception:
                memory_retrieve_status = "fallback-empty"
                if pending_store_content:
                    memory_store_flush_status = "failed"
                    _requeue_pending_memory_front(request.user_id, pending_store_content)

        async def _decide_routing():
            """LLM 路由决策任务（可与 Memory 并行）。"""
            nonlocal routed_to_agent, route_reason
            if routed_to_agent or request.force_chat_only:
                return
            try:
                decision = await _run_llm_job(
                    decide_agent_routing,
                    system_prompt=system_prompt,
                    model_name=model_name,
                    prompt=request.query,
                    memory_context="",  # Phase 1 阶段先不带 memory，等 Phase 2 用完整 memory
                )
                routed_to_agent = decision.should_trigger
                route_reason = decision.reason or "semantic_router"
            except Exception:
                routed_to_agent = False
                route_reason = "routing-error-fallback"

        memory_text = ""
        memory_retrieve_status = "ok"
        memory_store_flush_status = "skipped"

        # 并行执行 Phase 1 的两个独立任务
        await asyncio.gather(_fetch_memory(), _decide_routing())

        # ══════════════════════════════════════════════════════════
        # Phase 2 — 串行（依赖 Phase 1 结果）: Agent / LLM 生成
        # ══════════════════════════════════════════════════════════
        agent_mode = "skipped"
        if routed_to_agent:
            if _is_open("agent"):
                answer = "Agent 服务当前熔断中，已暂时降级为文本回复。"
                agent_mode = "circuit-open"
                routed_to_agent = False
            else:
                try:
                    agent_result = await post_json(
                        f"{AGENT_SERVICE_URL}/execute",
                        payload={"task": request.query, "user_id": request.user_id, "priority": "normal"},
                        timeout=AGENT_TIMEOUT_SEC,
                        headers=_request_headers(request_id),
                    )
                    answer = agent_result.get("result", "agent returned empty result")
                    agent_mode = agent_result.get("mode", "unknown")
                    _record_success("agent")
                except Exception:
                    _record_failure("agent")
                    routed_to_agent = False
                    answer = await _run_llm_job(call_llm, system_prompt, model_name, request.query, memory_text)
                    route_reason = f"{route_reason}|agent-failed-fallback-chat"
                    agent_mode = "fallback-chat"
        else:
            answer = await _run_llm_job(call_llm, system_prompt, model_name, request.query, memory_text)

        # ══════════════════════════════════════════════════════════
        # Phase 3 — 并行: TTS 语音合成 + Memory 延迟写入
        # ══════════════════════════════════════════════════════════
        _enqueue_pending_memory_write(
            request.user_id,
            f"用户: {request.query}\nAI: {answer}",
        )

        # TTS 和返回响应并行：TTS 不阻塞用户看到文字回复
        tts_future = asyncio.ensure_future(_submit_voice_with_batch_scheduler(answer, request_id))

        return {
            "answer": answer,
            "memory_context": memory_text,
            "tts": await tts_future,
            "routed_to_agent": routed_to_agent,
            "route_reason": route_reason,
            "model_name": model_name,
            "agent_mode": agent_mode,
            "memory_retrieve_status": memory_retrieve_status,
            "memory_store_status": "deferred",
            "memory_store_flush_status": memory_store_flush_status,
            "request_id": request_id,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"downstream service failure: {e}")
