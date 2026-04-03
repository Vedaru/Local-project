import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from modules.config import load_config
from modules.llm import call_llm, decide_agent_routing
from microservices.shared.http_client import post_json

app = FastAPI(title="project-local-orchestrator", version="0.1.0")

MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:8082")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://localhost:8083")
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://localhost:8084")

MEMORY_TIMEOUT_SEC = float(os.getenv("ORCH_MEMORY_TIMEOUT_SEC", "8"))
AGENT_TIMEOUT_SEC = float(os.getenv("ORCH_AGENT_TIMEOUT_SEC", "180"))
VOICE_TIMEOUT_SEC = float(os.getenv("ORCH_VOICE_TIMEOUT_SEC", "8"))

CIRCUIT_FAIL_THRESHOLD = int(os.getenv("ORCH_CIRCUIT_FAIL_THRESHOLD", "3"))
CIRCUIT_COOLDOWN_SEC = float(os.getenv("ORCH_CIRCUIT_COOLDOWN_SEC", "30"))


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: float = 0.0


_CIRCUITS = {
    "agent": CircuitState(),
    "voice": CircuitState(),
}


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
    }


@app.post("/chat")
async def chat(request: ChatRequest, http_request: Request) -> dict:
    try:
        request_id = http_request.headers.get("x-request-id", "")
        memory_context = await post_json(
            f"{MEMORY_SERVICE_URL}/retrieve",
            payload={"query": request.query, "user_id": request.user_id, "n_results": 4},
            timeout=MEMORY_TIMEOUT_SEC,
            headers=_request_headers(request_id),
        )
        memory_text = memory_context.get("context", "")

        cfg = load_config()
        system_prompt = cfg.system_prompt or ""
        model_name = cfg.model_name or ""

        routed_to_agent = bool(request.route_to_agent)
        route_reason = "forced_by_request" if routed_to_agent else ""

        if not routed_to_agent and not request.force_chat_only:
            decision = decide_agent_routing(
                system_prompt=system_prompt,
                model_name=model_name,
                prompt=request.query,
                memory_context=memory_text,
            )
            routed_to_agent = decision.should_trigger
            route_reason = decision.reason or "semantic_router"

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
                    answer = call_llm(system_prompt, model_name, request.query, memory_text)
                    route_reason = f"{route_reason}|agent-failed-fallback-chat"
                    agent_mode = "fallback-chat"
        else:
            answer = call_llm(system_prompt, model_name, request.query, memory_text)

        await post_json(
            f"{MEMORY_SERVICE_URL}/store",
            payload={
                "content": f"用户: {request.query}\\nAI: {answer}",
                "user_id": request.user_id,
            },
            timeout=MEMORY_TIMEOUT_SEC,
            headers=_request_headers(request_id),
        )

        if _is_open("voice"):
            tts = {
                "status": "skipped",
                "mode": "circuit-open",
                "reason": "voice circuit open",
            }
        else:
            try:
                tts = await post_json(
                    f"{VOICE_SERVICE_URL}/speak",
                    payload={"text": answer, "voice": "default"},
                    timeout=VOICE_TIMEOUT_SEC,
                    headers=_request_headers(request_id),
                )
                _record_success("voice")
            except Exception:
                _record_failure("voice")
                tts = {
                    "status": "skipped",
                    "mode": "fallback-no-voice",
                    "reason": "voice service unavailable",
                }

        return {
            "answer": answer,
            "memory_context": memory_text,
            "tts": tts,
            "routed_to_agent": routed_to_agent,
            "route_reason": route_reason,
            "model_name": model_name,
            "agent_mode": agent_mode,
            "request_id": request_id,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"downstream service failure: {e}")
