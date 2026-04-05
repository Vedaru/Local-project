import asyncio
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="project-local-memory-service", version="0.1.0")

_MEMORY_STORE = defaultdict(lambda: deque(maxlen=30))
_REAL_MEMORY_MANAGER: Optional[object] = None
_MEMORY_INIT_ERROR = ""


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    n_results: int = Field(default=3, ge=1, le=20)


class StoreRequest(BaseModel):
    content: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")


class BatchRequest(BaseModel):
    query: str = Field(default="")
    user_id: str = Field(default="anonymous")
    n_results: int = Field(default=4, ge=1, le=20)
    retrieve: bool = Field(default=True)
    store_content: str = Field(default="")


def _try_init_real_memory() -> None:
    global _REAL_MEMORY_MANAGER
    global _MEMORY_INIT_ERROR

    try:
        from modules.memory.wrapper import MemoryManager

        _REAL_MEMORY_MANAGER = MemoryManager()
        _MEMORY_INIT_ERROR = ""
    except Exception as exc:
        _REAL_MEMORY_MANAGER = None
        _MEMORY_INIT_ERROR = str(exc)


@app.on_event("startup")
async def startup_event() -> None:
    await asyncio.to_thread(_try_init_real_memory)


@app.get("/health")
async def health() -> dict:
    if _REAL_MEMORY_MANAGER is None:
        return {
            "status": "degraded",
            "service": "memory-service",
            "mode": "fallback-in-memory",
            "error": _MEMORY_INIT_ERROR,
            "items": sum(len(v) for v in _MEMORY_STORE.values()),
        }

    stats = await asyncio.to_thread(_REAL_MEMORY_MANAGER.get_memory_stats)
    return {
        "status": "ok",
        "service": "memory-service",
        "mode": "real-memory-manager",
        "error": "",
        "stats": stats,
    }


@app.post("/retrieve")
async def retrieve(request: RetrieveRequest) -> dict:
    if _REAL_MEMORY_MANAGER is not None:
        context = await asyncio.to_thread(
            _REAL_MEMORY_MANAGER.retrieve_memories,
            f"[{request.user_id}] {request.query}",
            request.n_results,
        )
        return {
            "context": context or "",
            "query": request.query,
            "mode": "real-memory-manager",
        }

    history = list(_MEMORY_STORE[request.user_id])
    if history:
        context = "\n".join(history[-5:])
    else:
        context = ""
    return {
        "context": context,
        "query": request.query,
        "mode": "fallback-in-memory",
    }


@app.post("/store")
async def store(request: StoreRequest) -> dict:
    if _REAL_MEMORY_MANAGER is not None:
        await asyncio.to_thread(
            _REAL_MEMORY_MANAGER.store_memory,
            f"用户({request.user_id}): {request.content}",
        )
        return {
            "status": "stored",
            "count": -1,
            "mode": "real-memory-manager",
        }

    _MEMORY_STORE[request.user_id].append(request.content)
    return {
        "status": "stored",
        "count": len(_MEMORY_STORE[request.user_id]),
        "mode": "fallback-in-memory",
    }


@app.post("/batch")
async def batch(request: BatchRequest) -> dict:
    """原子化检索+存储接口，一次 HTTP 往返完成两件事。"""
    context = ""
    retrieve_status = "ok"
    store_status = ""

    if request.retrieve and request.query.strip():
        try:
            if _REAL_MEMORY_MANAGER is not None:
                ctx = await asyncio.to_thread(
                    _REAL_MEMORY_MANAGER.retrieve_memories,
                    f"[{request.user_id}] {request.query}",
                    request.n_results,
                )
                context = ctx or ""
                if not context:
                    retrieve_status = "empty"
            else:
                history = list(_MEMORY_STORE[request.user_id])
                context = "\n".join(history[-5:]) if history else ""
                retrieve_status = "fallback"
        except Exception as exc:
            retrieve_status = f"failed:{exc}"
    elif not request.retrieve:
        retrieve_status = "skipped"

    if request.store_content and request.store_content.strip():
        try:
            if _REAL_MEMORY_MANAGER is not None:
                await asyncio.to_thread(
                    _REAL_MEMORY_MANAGER.store_memory,
                    f"用户({request.user_id}): {request.store_content}",
                )
            else:
                _MEMORY_STORE[request.user_id].append(request.store_content)
            store_status = "stored"
        except Exception:
            store_status = "failed"

    return {
        "context": context,
        "query": request.query,
        "retrieve_status": retrieve_status,
        "store_status": store_status,
        "mode": "real-memory-manager" if _REAL_MEMORY_MANAGER else "fallback-in-memory",
    }
