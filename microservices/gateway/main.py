"""
Gateway 微服务 — API 入口、认证、请求转发

配置来源优先级:
  1. 环境变量（显式设置，用于容器化部署覆盖）
  2. tuning.yaml（通过 modules.config_tuning.load_tuning()）
  3. 内置默认值

超时推导:
  如果 GATEWAY_CHAT_TIMEOUT_SEC 未显式设置，
  自动从 TuningConfig.orchestrator 的子超时计算:
    gateway_timeout = memory + max(agent, voice) + 余量
"""

# ruff: noqa: E402

import asyncio
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

# 将项目根目录加入 sys.path，确保能 import modules
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from microservices.shared.http_client import get_json, post_json
from modules.logging_config import get_logger
from modules.python_runtime_guard import ensure_supported_python_runtime

app = FastAPI(title="project-local-gateway", version="0.1.0")
logger = get_logger("Gateway")

# ---- 从 TuningConfig 读取服务地址与超时（统一配置源） ----
def _load_tuning_or_defaults():
    """尝试从 TuningConfig 加载；失败则回退到环境变量 + 默认值。"""
    try:
        from modules.config_tuning import load_tuning
        t = load_tuning()
        svc = t.services
        orch = t.orchestrator
        gw = t.gateway
        return {
            "orchestrator_url": svc.orchestrator_url,
            "memory_service_url": svc.memory_service_url,
            "agent_service_url": svc.agent_service_url,
            "voice_service_url": svc.voice_service_url,
            "gateway_port": str(svc.gateway_port),
            "api_key": gw.api_key,
            # 超时：如果 tuning.yaml 中已显式设置 chat_timeout_sec 则直接用
            # 否则自动推导 = memory + max(agent, voice) + 余量
            "chat_timeout_sec": gw.chat_timeout_sec if gw.chat_timeout_sec > 0
            else round(orch.memory_timeout_sec + max(orch.agent_timeout_sec, orch.voice_timeout_sec), 1),
        }
    except Exception:
        # 回退：纯环境变量 + 推导逻辑（向后兼容旧部署方式）
        _mem = float(os.getenv("ORCH_MEMORY_TIMEOUT_SEC", "8") or "8")
        _agent = float(os.getenv("ORCH_AGENT_TIMEOUT_SEC", "180") or "180")
        _voice = float(os.getenv("ORCH_VOICE_TIMEOUT_SEC", "60") or "60")
        _explicit_timeout = os.getenv("GATEWAY_CHAT_TIMEOUT_SEC", "").strip()
        return {
            "orchestrator_url": os.getenv("ORCHESTRATOR_URL", "http://localhost:18081"),
            "memory_service_url": os.getenv("MEMORY_SERVICE_URL", "http://localhost:18082"),
            "agent_service_url": os.getenv("AGENT_SERVICE_URL", "http://localhost:18083"),
            "voice_service_url": os.getenv("VOICE_SERVICE_URL", "http://localhost:18084"),
            "gateway_port": os.getenv("GATEWAY_PORT", "18080"),
            "api_key": (os.getenv("GATEWAY_API_KEY", "") or "").strip(),
            "chat_timeout_sec": float(_explicit_timeout) if _explicit_timeout
            else round(_mem + max(_agent, _voice), 1),
        }


_cfg = _load_tuning_or_defaults()

ORCHESTRATOR_URL: str = _cfg["orchestrator_url"]
MEMORY_SERVICE_URL: str = _cfg["memory_service_url"]
AGENT_SERVICE_URL: str = _cfg["agent_service_url"]
VOICE_SERVICE_URL: str = _cfg["voice_service_url"]
GATEWAY_API_KEY: str = _cfg["api_key"]
GATEWAY_PORT: str = _cfg["gateway_port"]
GATEWAY_CHAT_TIMEOUT_SEC: float = _cfg["chat_timeout_sec"]


@app.middleware("http")
async def tracing_and_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    if GATEWAY_API_KEY and request.url.path.startswith("/v1/"):
        header_key = (request.headers.get("x-api-key") or "").strip()
        bearer = (request.headers.get("authorization") or "").strip()
        bearer_key = bearer[7:].strip() if bearer.lower().startswith("bearer ") else ""
        if header_key != GATEWAY_API_KEY and bearer_key != GATEWAY_API_KEY:
            from microservices.shared.types import ErrorResult
            err = ErrorResult(
                status="error",
                code="unauthorized",
                message="missing or invalid API key",
                request_id=request_id,
            ).to_dict()
            return JSONResponse(
                status_code=401,
                content=err,
                headers={"x-request-id": request_id},
            )

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


async def _probe_service(service_name: str, base_url: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    health_url = f"{base_url.rstrip('/')}/health"
    try:
        payload = await get_json(health_url, timeout=3.0)
        latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        return {
            "service": service_name,
            "url": health_url,
            "ok": True,
            "latency_ms": latency_ms,
            "payload": payload,
            "error": "",
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        return {
            "service": service_name,
            "url": health_url,
            "ok": False,
            "latency_ms": latency_ms,
            "payload": {},
            "error": str(exc),
        }


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    route_to_agent: bool = Field(default=False)


@app.on_event("startup")
async def startup_event() -> None:
    ensure_supported_python_runtime(logger=logger)


@app.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": "gateway",
        "request_id": getattr(request.state, "request_id", ""),
        "auth_enabled": bool(GATEWAY_API_KEY),
    }


@app.get("/v1/status/services")
async def service_status(request: Request) -> dict:
    # 5 个健康检查全部并行执行（15s → ~3s）
    checks = await asyncio.gather(
        _probe_service("gateway", f"http://localhost:{GATEWAY_PORT}"),
        _probe_service("orchestrator", ORCHESTRATOR_URL),
        _probe_service("memory-service", MEMORY_SERVICE_URL),
        _probe_service("agent-service", AGENT_SERVICE_URL),
        _probe_service("voice-service", VOICE_SERVICE_URL),
        return_exceptions=True,
    )
    # 将异常转换为失败结果
    normalized: list[dict[str, object]] = []
    for c in checks:
        if isinstance(c, BaseException):
            normalized.append({
                "service": "unknown",
                "url": "",
                "ok": False,
                "latency_ms": 0,
                "payload": {},
                "error": str(c),
            })
        else:
            normalized.append(c)
    healthy_count = sum(1 for item in normalized if item["ok"])
    return {
        "overall_ok": healthy_count == len(normalized),
        "healthy": healthy_count,
        "total": len(normalized),
        "services": normalized,
        "request_id": getattr(request.state, "request_id", ""),
    }


@app.post("/v1/chat")
async def chat(request: ChatRequest, http_request: Request) -> dict:
    try:
        request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
        result = await post_json(
            f"{ORCHESTRATOR_URL}/chat",
            payload=request.model_dump(),
            timeout=GATEWAY_CHAT_TIMEOUT_SEC,
            headers={"x-request-id": request_id},
        )
        result["request_id"] = request_id
        return result
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"orchestrator unavailable: {e}",
                "request_id": getattr(http_request.state, "request_id", ""),
            },
        )
