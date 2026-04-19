"""
Orchestrator microservice — main entry point

Refactored: delegates all mutable state to OrchestratorCore instance.
This file retains only FastAPI routes and wiring.
"""

import asyncio
import contextlib
import threading
import uuid
from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import Response

from microservices.orchestrator.core import OrchestratorConfig, OrchestratorCore
from modules.logging_config import clear_context, get_logger, set_context
from modules.python_runtime_guard import ensure_supported_python_runtime

app = FastAPI(title="project-local-orchestrator", version="0.2.0")
logger = get_logger("Orchestrator")


@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    rid = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
    set_context(request_id=rid)
    try:
        response = await call_next(request)
        response.headers.setdefault("x-request-id", rid)
        return response
    finally:
        clear_context()


# Singleton core instance (legacy compat with tests)
_core: Optional[OrchestratorCore] = None
_core_cfg: Optional[OrchestratorConfig] = None
_core_lock = threading.Lock()


def _get_cached_core() -> tuple[Optional[OrchestratorCore], Optional[OrchestratorConfig]]:
    core = getattr(app.state, "orchestrator_core", None)
    cfg = getattr(app.state, "orchestrator_core_cfg", None)
    return core, cfg


def _set_cached_core(core: Optional[OrchestratorCore], cfg: Optional[OrchestratorConfig]) -> None:
    global _core, _core_cfg
    app.state.orchestrator_core = core
    app.state.orchestrator_core_cfg = cfg
    _core = core
    _core_cfg = cfg


def reset_core_for_tests() -> None:
    """Reset cached orchestrator core for isolated tests."""
    with _core_lock:
        cached_core, _ = _get_cached_core()
        if cached_core is None:
            cached_core = _core
        if cached_core is not None:
            with contextlib.suppress(Exception):
                cached_core.shutdown()
        _set_cached_core(None, None)


def get_core() -> OrchestratorCore:
    """Get (or lazily create) the orchestrator core singleton."""
    expected_cfg = OrchestratorConfig.from_env()
    with _core_lock:
        # Backward compatibility: tests may set module-level _core=None
        # to force recreation under new environment values.
        if _core is None and getattr(app.state, "orchestrator_core", None) is not None:
            _set_cached_core(None, None)

        cached_core, cached_cfg = _get_cached_core()
        if cached_core is None or cached_cfg != expected_cfg:
            if cached_core is not None:
                with contextlib.suppress(Exception):
                    cached_core.shutdown()
            cached_core = OrchestratorCore(config=expected_cfg)
            _set_cached_core(cached_core, expected_cfg)
        return cached_core


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    route_to_agent: bool = Field(default=False)
    force_chat_only: bool = Field(default=False)


@app.get("/health")
async def health() -> dict:
    core = get_core()
    health_data = core.health_snapshot()

    # Add time-based fields that require current time
    for _name, circuit_info in health_data["circuits"].items():
        circuit_info["open_remaining_sec"] = max(0.0, circuit_info.get("open_remaining_sec", 0))

    return {
        "status": "ok",
        "service": "orchestrator",
        **health_data,
    }


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize app.state cache slots on startup."""
    ensure_supported_python_runtime(logger=logger)
    with _core_lock:
        if not hasattr(app.state, "orchestrator_core"):
            _set_cached_core(None, None)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    with _core_lock:
        core, _ = _get_cached_core()
        if core is None:
            core = _core
        _set_cached_core(None, None)

    if core is not None:
        core.shutdown()
        await core.flush_pending_memory_writes_on_shutdown()
        await core.shutdown_voice_batch_worker()

    from microservices.shared.http_client import close_http_clients

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
        core = get_core()
        if not core.try_acquire_token():
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers={"Retry-After": f"{core.estimate_retry_after_sec():.2f}"},
            )

        cfg = core.cfg
        request_id = http_request.headers.get("x-request-id", "")
        pending_store_content = core.dequeue_pending_memory_write(request.user_id)

        from modules.config import get_cached_config

        app_cfg = get_cached_config()
        system_prompt = app_cfg.system_prompt or ""
        model_name = app_cfg.model_name or ""

        # ══════════════════════════════════════════════════════════
        # Phase 1 — 并行启动: Memory 批处理 + 路由决策
        # ══════════════════════════════════════════════════════════
        routed_to_agent = bool(request.route_to_agent)
        route_reason = "forced_by_request" if routed_to_agent else ""
        memory_text = ""
        memory_retrieve_status = "ok"
        memory_store_flush_status = "skipped"

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
                    "store_content": pending_store_content or "",
                }
                ctx = await __import_post_json()(  # type: ignore
                    f"{cfg.memory_service_url}/batch",
                    payload=payload,
                    timeout=cfg.memory_batch_timeout_sec,
                    headers={"x-request-id": request_id},
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
                        core.requeue_pending_memory_front(request.user_id, pending_store_content)
            except Exception as exc:
                logger.warning("memory batch request failed: %s", exc)
                memory_retrieve_status = "fallback-empty"
                if pending_store_content:
                    memory_store_flush_status = "failed"
                    core.requeue_pending_memory_front(request.user_id, pending_store_content)

        async def _decide_routing():
            """LLM 路由决策任务（可与 Memory 并行）。"""
            nonlocal routed_to_agent, route_reason
            if routed_to_agent or request.force_chat_only:
                return
            try:
                from modules.llm import decide_agent_routing

                decision = await core.run_llm_job(
                    decide_agent_routing,
                    system_prompt=system_prompt,
                    model_name=model_name,
                    prompt=request.query,
                    memory_context="",
                )
                routed_to_agent = decision.should_trigger
                route_reason = decision.reason or "semantic_router"
            except Exception as exc:
                logger.warning("semantic routing failed, fallback chat: %s", exc)
                routed_to_agent = False
                route_reason = "routing-error-fallback"

        # 并行执行 Phase 1 的两个独立任务
        await asyncio.gather(_fetch_memory(), _decide_routing())

        # ══════════════════════════════════════════════════════════
        # Phase 2 — 串行（依赖 Phase 1 结果）: Agent / LLM 生成
        # ══════════════════════════════════════════════════════════
        streamed_tts_payloads: list[dict] = []

        async def _run_llm_with_streaming_tts(query: str, memory_ctx: str) -> tuple[str, list[dict]]:
            """在 LLM 生成首句时立即触发 TTS 分片任务。"""
            loop = asyncio.get_running_loop()
            streaming_futures = []
            streaming_futures_lock = threading.Lock()

            def _on_sentence_ready(sentence: str) -> None:
                normalized = str(sentence or "").strip()
                if not normalized:
                    return
                fut = asyncio.run_coroutine_threadsafe(
                    core.submit_voice_with_batch_scheduler(normalized, request_id),
                    loop,
                )
                with streaming_futures_lock:
                    streaming_futures.append(fut)

            try:
                from modules.llm import call_llm_with_sentence_callback

                answer_text = await core.run_llm_job(
                    call_llm_with_sentence_callback,
                    system_prompt,
                    model_name,
                    query,
                    memory_ctx,
                    _on_sentence_ready,
                )
                with streaming_futures_lock:
                    futures_snapshot = list(streaming_futures)
                if not futures_snapshot:
                    return answer_text, []
                wrapped = [asyncio.wrap_future(item) for item in futures_snapshot]
                results = await asyncio.gather(*wrapped, return_exceptions=True)
                payloads = [item for item in results if isinstance(item, dict)]
                return answer_text, payloads
            except Exception as exc:
                logger.debug("streamed llm path unavailable, fallback normal llm: %s", exc)
                from modules.llm import call_llm

                answer_text = await core.run_llm_job(
                    call_llm,
                    system_prompt,
                    model_name,
                    query,
                    memory_ctx,
                )
                return answer_text, []

        prewarm_task = asyncio.create_task(core.prewarm_voice_openers(request_id))

        agent_mode = "skipped"
        if routed_to_agent:
            if core.is_circuit_open("agent"):
                answer = "Agent 服务当前熔断中，已暂时降级为文本回复。"
                agent_mode = "circuit-open"
                routed_to_agent = False
            else:
                try:
                    agent_result = await __import_post_json()(
                        f"{cfg.agent_service_url}/execute",
                        payload={
                            "task": request.query,
                            "user_id": request.user_id,
                            "priority": "normal",
                        },
                        timeout=cfg.agent_timeout_sec,
                        headers={"x-request-id": request_id},
                    )
                    answer = agent_result.get("result", "agent returned empty result")
                    agent_mode = agent_result.get("mode", "unknown")
                    core.record_circuit_success("agent")
                except Exception:
                    core.record_circuit_failure("agent")
                    routed_to_agent = False
                    answer, streamed_tts_payloads = await _run_llm_with_streaming_tts(
                        request.query,
                        memory_text,
                    )
                    route_reason = f"{route_reason}|agent-failed-fallback-chat"
                    agent_mode = "fallback-chat"
        else:
            answer, streamed_tts_payloads = await _run_llm_with_streaming_tts(
                request.query,
                memory_text,
            )

        with contextlib.suppress(Exception):
            await prewarm_task

        # ══════════════════════════════════════════════════════════
        # Phase 3 — 并行: TTS语音合成 + Memory 延迟写入入队
        # ══════════════════════════════════════════════════════════
        core.enqueue_pending_memory_write(
            request.user_id,
            f"用户: {request.query}\nAI: {answer}",
        )

        if streamed_tts_payloads:
            flattened_segments: list[dict] = []
            for payload in streamed_tts_payloads:
                nested = payload.get("segments")
                if isinstance(nested, list) and nested:
                    for segment in nested:
                        if isinstance(segment, dict):
                            flattened_segments.append(dict(segment))
                else:
                    flattened_segments.append(dict(payload))

            if flattened_segments:
                tts_payload = core.merge_voice_segments(answer, flattened_segments, request_id)
            else:
                tts_payload = await core.submit_voice_with_batch_scheduler(answer, request_id)
        else:
            tts_payload = await core.submit_voice_with_batch_scheduler(answer, request_id)

        return {
            "answer": answer,
            "memory_context": memory_text,
            "tts": tts_payload,
            "routed_to_agent": routed_to_agent,
            "route_reason": route_reason,
            "model_name": model_name,
            "agent_mode": agent_mode,
            "memory_retrieve_status": memory_retrieve_status,
            "memory_store_status": "deferred",
            "memory_store_flush_status": memory_store_flush_status,
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"downstream service failure: {e}")


def __import_post_json():
    """Lazy import to avoid circular dependency at module load."""
    from microservices.shared.http_client import post_json

    return post_json
