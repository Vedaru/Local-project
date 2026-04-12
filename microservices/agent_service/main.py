import asyncio
import os
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from modules.logging_config import get_logger
from modules.python_runtime_guard import ensure_supported_python_runtime

app = FastAPI(title="project-local-agent-service", version="0.1.0")
logger = get_logger("AgentService")


class AgentRuntime(Protocol):
    def cleanup(self) -> None: ...
    def run_task(self, task_description: str) -> str: ...
    def request_cancel(self) -> bool: ...


_REAL_AGENT: AgentRuntime | None = None
_AGENT_INIT_ERROR = ""


def _try_init_agent() -> None:
    global _REAL_AGENT
    global _AGENT_INIT_ERROR

    try:
        from modules.agent.core import ManusAgent
        from modules.config import get_cached_config

        cfg = get_cached_config()
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
    ensure_supported_python_runtime(logger=logger)
    await asyncio.to_thread(_try_init_agent)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _REAL_AGENT is not None:
        await asyncio.to_thread(_REAL_AGENT.cleanup)


class ExecuteRequest(BaseModel):
    task: str = Field(min_length=1, max_length=10000)
    user_id: str = Field(default="anonymous", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    priority: str = Field(default="normal", pattern=r"^(low|normal|high|critical)$")
    timeout_seconds: float = Field(default=180.0, ge=5.0, le=1800.0)

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        dangerous_patterns = (
            r";\s*rm\s+-rf",
            r"`.*?`",
            r"\$\(.*?\)",
            r"<script.*?>",
            r"javascript:",
        )
        normalized = (value or "").strip()
        for pattern in dangerous_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                raise ValueError("Task contains potentially dangerous pattern")
        return normalized

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        return normalized or "anonymous"


class InputValidator:
    """输入净化与基本安全校验工具。"""

    @staticmethod
    def sanitize_path(path: str) -> str:
        normalized = str(path or "").replace("\x00", "")
        if not normalized.strip():
            raise ValueError("Invalid path")
        try:
            return str(Path(normalized).resolve())
        except Exception as exc:
            raise ValueError("Invalid path") from exc

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only HTTP/HTTPS URLs are allowed")
        if not parsed.netloc:
            raise ValueError("URL is missing host")
        return url


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

    try:
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
    except asyncio.TimeoutError as exc:
        logger.error("Agent execution timeout after %.2fs", request.timeout_seconds)
        raise HTTPException(
            status_code=504,
            detail={
                "error": f"Task timeout after {request.timeout_seconds}s",
                "error_code": "AGENT_TIMEOUT",
            },
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error in agent execution")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(exc),
                "error_code": "AGENT_EXECUTION_ERROR",
            },
        ) from exc


@app.post("/cancel")
async def cancel() -> dict:
    if _REAL_AGENT is None:
        return {"status": "noop", "mode": "fallback-echo"}

    cancelled = await asyncio.to_thread(_REAL_AGENT.request_cancel)
    return {
        "status": "cancel-requested" if cancelled else "idle",
        "mode": "real-manus-agent",
    }
