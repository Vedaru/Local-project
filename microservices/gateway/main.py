import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from microservices.shared.http_client import get_json, post_json

app = FastAPI(title="project-local-gateway", version="0.1.0")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8081")
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:8082")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://localhost:8083")
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://localhost:8084")
GATEWAY_API_KEY = (os.getenv("GATEWAY_API_KEY", "") or "").strip()

# Gateway 超时配置：支持显式设置，或从 orchestrator 子超时推导
_GATEWAY_CHAT_TIMEOUT_ENV = os.getenv("GATEWAY_CHAT_TIMEOUT_SEC", "")
if _GATEWAY_CHAT_TIMEOUT_ENV.strip():
    GATEWAY_CHAT_TIMEOUT_SEC = float(_GATEWAY_CHAT_TIMEOUT_ENV.strip())
else:
    _mem = float(os.getenv("ORCH_MEMORY_TIMEOUT_SEC", "8") or "8")
    _agent = float(os.getenv("ORCH_AGENT_TIMEOUT_SEC", "180") or "180")
    _voice = float(os.getenv("ORCH_VOICE_TIMEOUT_SEC", "60") or "60")
    # 默认 = memory + max(agent, voice)，留余量
    GATEWAY_CHAT_TIMEOUT_SEC = round(_mem + max(_agent, _voice), 1)


@app.middleware("http")
async def tracing_and_auth_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    if GATEWAY_API_KEY and request.url.path.startswith("/v1/"):
        header_key = (request.headers.get("x-api-key") or "").strip()
        bearer = (request.headers.get("authorization") or "").strip()
        bearer_key = bearer[7:].strip() if bearer.lower().startswith("bearer ") else ""
        if header_key != GATEWAY_API_KEY and bearer_key != GATEWAY_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "unauthorized", "request_id": request_id},
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
        _probe_service("gateway", "http://localhost:" + os.getenv("GATEWAY_PORT", "8080")),
        _probe_service("orchestrator", ORCHESTRATOR_URL),
        _probe_service("memory-service", MEMORY_SERVICE_URL),
        _probe_service("agent-service", AGENT_SERVICE_URL),
        _probe_service("voice-service", VOICE_SERVICE_URL),
        return_exceptions=True,
    )
    # 将异常转换为失败结果
    normalized = []
    for c in checks:
        if isinstance(c, Exception):
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
