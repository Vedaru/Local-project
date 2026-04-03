import asyncio
import os
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="project-local-agent-service", version="0.1.0")

_REAL_AGENT: Optional[object] = None
_AGENT_INIT_ERROR = ""


def _try_init_agent() -> None:
    global _REAL_AGENT
    global _AGENT_INIT_ERROR

    try:
        from modules.agent.core import ManusAgent
        from modules.config import load_config

        cfg = load_config()
        max_steps = int(os.getenv("AGENT_MAX_STEPS", str(cfg.agent_max_steps)))
        timeout_s = float(os.getenv("AGENT_TASK_TIMEOUT_SECONDS", str(cfg.agent_task_timeout_seconds)))

        _REAL_AGENT = ManusAgent(
            system_prompt=cfg.system_prompt or "",
            max_steps=max_steps,
            task_timeout_seconds=timeout_s,
        )
        _AGENT_INIT_ERROR = ""
    except Exception as exc:
        _REAL_AGENT = None
        _AGENT_INIT_ERROR = str(exc)


@app.on_event("startup")
async def startup_event() -> None:
    await asyncio.to_thread(_try_init_agent)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _REAL_AGENT is not None:
        await asyncio.to_thread(_REAL_AGENT.cleanup)


class ExecuteRequest(BaseModel):
    task: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    priority: str = Field(default="normal")
    timeout_seconds: float = Field(default=180.0, ge=5.0, le=1800.0)


@app.get("/health")
async def health() -> dict:
    if _REAL_AGENT is None:
        return {
            "status": "degraded",
            "service": "agent-service",
            "mode": "fallback-echo",
            "error": _AGENT_INIT_ERROR,
        }

    return {
        "status": "ok",
        "service": "agent-service",
        "mode": "real-manus-agent",
        "error": "",
    }


@app.post("/execute")
async def execute(request: ExecuteRequest) -> dict:
    if _REAL_AGENT is None:
        result = f"[agent fallback] task executed for {request.user_id}: {request.task}"
        return {
            "result": result,
            "priority": request.priority,
            "mode": "fallback-echo",
        }

    task_desc = f"[user={request.user_id}] {request.task}"
    result = await asyncio.wait_for(
        asyncio.to_thread(_REAL_AGENT.run_task, task_desc),
        timeout=request.timeout_seconds,
    )
    return {
        "result": result,
        "priority": request.priority,
        "mode": "real-manus-agent",
    }


@app.post("/cancel")
async def cancel() -> dict:
    if _REAL_AGENT is None:
        return {"status": "noop", "mode": "fallback-echo"}

    cancelled = await asyncio.to_thread(_REAL_AGENT.request_cancel)
    return {
        "status": "cancel-requested" if cancelled else "idle",
        "mode": "real-manus-agent",
    }
