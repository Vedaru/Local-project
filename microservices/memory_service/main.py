"""
Memory Service (microservice) — Engram-based memory storage/retrieval.

HTTP API:
  POST /batch   — batch store + retrieve
  GET  /stats    — memory statistics
  GET  /health   — health check
"""

import asyncio
import logging
import os
import signal
import threading
import time

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from typing import Optional
import uvicorn

from modules.memory import HumanMemoryEngine
from modules.python_runtime_guard import ensure_supported_python_runtime

logger = logging.getLogger("MemoryService")

# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_engine: HumanMemoryEngine | None = None
_engine_lock = threading.Lock()


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_BATCH_DISABLE_FACT_EXTRACTION = _read_bool_env("MEMORY_BATCH_DISABLE_FACT_EXTRACTION", True)
_BATCH_DEFERRED_PERSIST = _read_bool_env("MEMORY_BATCH_DEFERRED_PERSIST", True)


def _get_cached_engine() -> HumanMemoryEngine | None:
    return getattr(app.state, "memory_engine", None)


def _set_cached_engine(engine: HumanMemoryEngine | None) -> None:
    global _engine
    app.state.memory_engine = engine
    _engine = engine


def reset_engine_for_tests() -> None:
    """Reset cached engine for isolated test scenarios."""
    with _engine_lock:
        engine = _get_cached_engine() or _engine
        _set_cached_engine(None)
    if engine is not None:
        try:
            engine.close()
        except Exception:
            pass


def _create_llm_extract_fn():
    """
    创建 LLM 事实提取函数，用于从用户对话中提取结构化知识。

    返回一个 Callable[[str], dict]，输入为用户话语，输出为:
      {"facts": [{"fact": "用户喜欢香蕉", "category": "preference", "confidence": 0.9}, ...]}
    """
    try:
        from modules.llm import call_llm
    except ImportError:
        logger.warning("[LLM] modules.llm 导入失败，事实提取将不可用")
        return None

    def _extract_facts(user_text: str) -> dict:
        """调用 LLM 从用户话语中提取事实信息。"""
        if not user_text or not user_text.strip():
            return {"facts": []}

        # 从 AppConfig 获取真实模型名（回退到环境变量）
        _model_name = ""
        try:
            from modules.config import load_config
            cfg = load_config()
            _model_name = cfg.model_name or ""
        except Exception:
            pass
        if not _model_name:
            _model_name = os.environ.get("MODEL_NAME", "")

        if not _model_name:
            logger.warning("[LLM Fact Extraction] MODEL_NAME 未配置，跳过 LLM 提取")
            return {"facts": []}

        prompt = (
            "从以下用户话语中提取关于用户的个人偏好、喜好、事实信息。\n"
            "只提取明确的事实陈述，不要猜测或推断。\n"
            "返回严格的 JSON 格式，不要有其他文字。\n"
            '格式示例: {"facts": [{"fact": "事实内容", "category": "preference", "confidence": 0.9}]}\n\n'
            "用户话语: " + user_text
        )

        try:
            response = call_llm(
                system_prompt="你是一个信息提取助手。只返回 JSON 格式的事实列表，不要其他内容。",
                model_name=_model_name,
                prompt=prompt,
                max_retries=1,
            )
            # 尝试解析 JSON 响应
            import json
            import re

            text = str(response).strip()
            # 移除可能的 markdown 代码块标记
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'```\s*$', '', text)

            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return {"facts": []}
        except Exception as e:
            logger.debug(f"[LLM Fact Extraction] 提取失败: {e}")
            return {"facts": []}

    return _extract_facts


def _get_engine() -> HumanMemoryEngine:
    with _engine_lock:
        # Backward compatibility: tests may set module-level _engine=None
        # to force re-initialization.
        if _engine is None and _get_cached_engine() is not None:
            _set_cached_engine(None)

        engine = _get_cached_engine()
        if engine is None:
            logger.info("[初始化] 正在启动 HumanMemoryEngine...")
            llm_extract_fn = _create_llm_extract_fn()
            if llm_extract_fn:
                logger.info("[初始化] LLM 事实提取函数已就绪")
            else:
                logger.warning("[初始化] LLM 事实提取函数未创建，语义记忆将无法自动积累")
            engine = HumanMemoryEngine(
                base_dir=os.environ.get(
                    "MEMORY_DATA_DIR",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "memoripy"),
                ),
                llm_extract_fn=llm_extract_fn,
            )
            _set_cached_engine(engine)
        return engine


app = FastAPI(title="Memory Service (Engram)", version="2.0.0")


class BatchRequest(BaseModel):
    query: str = ""
    user_id: str = "local-user"
    n_results: int = Field(default=5, ge=1, le=20)
    retrieve: bool = True
    store_content: Optional[str] = None


@app.on_event("startup")
async def _startup():
    """Pre-initialize engine on startup."""
    ensure_supported_python_runtime(logger=logger)
    with _engine_lock:
        if not hasattr(app.state, "memory_engine"):
            _set_cached_engine(None)
    _get_engine()
    logger.info(f"MemoryService 就绪 | PID={os.getpid()}")


@app.on_event("shutdown")
async def _shutdown():
    reset_engine_for_tests()


def _health_sync() -> dict:
    """Health check sync worker."""
    try:
        eng = _get_engine()
        s = eng.stats()
        return {
            "status": "ok",
            "engine_ready": True,
            "working_memory": s["working_memory_count"],
            "engram_slots": s["engram_total_slots_used"],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "engine_ready": False}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return await asyncio.to_thread(_health_sync)


def _batch_sync(req: BatchRequest) -> dict:
    """Combined store + retrieve sync worker."""
    eng = _get_engine()
    result: dict = {
        "context": "",
        "retrieve_status": "ok",
        "store_status": "skipped",
    }

    # Store first (pending content from previous turn)
    if req.store_content and req.store_content.strip():
        try:
            eng.store(
                req.store_content,
                metadata={
                    "user_id": req.user_id,
                    "disable_fact_extraction": _BATCH_DISABLE_FACT_EXTRACTION,
                    "deferred_persist": _BATCH_DEFERRED_PERSIST,
                },
            )
            result["store_status"] = "stored"
            logger.info(f"[batch] 已存储内容 ({len(req.store_content)} chars)")
        except Exception as e:
            logger.error(f"[存储异常] {e}")
            result["store_status"] = "error"

    # Retrieve
    if req.retrieve and req.query:
        try:
            ctx = eng.retrieve(query=req.query, n_results=req.n_results, user_id=req.user_id)
            result["context"] = ctx or ""
        except Exception as e:
            logger.error(f"[检索异常] {e}")
            result["retrieve_status"] = "failed"
            result["context"] = ""

    return result


@app.post("/batch")
async def batch(req: BatchRequest):
    """
    Combined store + retrieve endpoint used by Orchestrator.

    Orchestrator sends:
      - store_content: pending interaction from previous turn (if any)
      - query: current query for retrieval

    Returns dict with 'context' string and status fields.
    Every store triggers immediate Engram disk persistence.
    """
    return await asyncio.to_thread(_batch_sync, req)


def _store_sync(content: str, user_id: str) -> dict:
    """Store sync worker."""
    eng = _get_engine()
    try:
        status = eng.store(content or "", metadata={"user_id": user_id})
        return {"status": status}
    except Exception as e:
        logger.error(f"[存储异常] {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/store")
async def do_store(content: str = ..., user_id: str = "local-user"):
    """Explicit store endpoint."""
    return await asyncio.to_thread(_store_sync, content, user_id)


def _stats_sync() -> dict:
    """Stats sync worker."""
    eng = _get_engine()
    return eng.stats()


@app.get("/stats")
async def stats():
    """Return memory statistics."""
    return await asyncio.to_thread(_stats_sync)


def _close_sync() -> dict:
    """Close sync worker."""
    engine = None
    with _engine_lock:
        engine = _get_cached_engine() or _engine
        _set_cached_engine(None)
    if engine is not None:
        try:
            engine.close()
            logger.info("[关闭] MemoryService 已关闭")
        except Exception as e:
            logger.error(f"[关闭] 异常: {e}")
    return {"status": "closed"}


@app.post("/close")
async def close():
    """Persist and release resources (for graceful shutdown)."""
    return await asyncio.to_thread(_close_sync)


def main(host: str = "127.0.0.1", port: int = 18082):
    """Entry point."""
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
