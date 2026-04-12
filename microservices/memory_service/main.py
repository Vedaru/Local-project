"""
Memory Service (microservice) — MemPalace-style memory storage/retrieval.

HTTP API:
  POST /batch   — batch store + retrieve
  GET  /stats    — memory statistics
  GET  /health   — health check
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from typing import Any, Optional

import uvicorn
from fastapi import Body, FastAPI
from pydantic import BaseModel, Field

from modules.memory import HumanMemoryEngine
from modules.python_runtime_guard import ensure_supported_python_runtime

logger = logging.getLogger("MemoryService")

# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_engine: HumanMemoryEngine | None = None
_engine_lock = threading.Lock()


def _normalize_user_id(user_id: str) -> str:
    key = str(user_id or "").strip()
    return key or "local-user"


def _default_memory_data_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "memoripy")


def _load_memory_runtime_settings() -> dict[str, object]:
    defaults: dict[str, object] = {
        "data_dir": _default_memory_data_dir(),
        "wal_path": "",
        "batch_disable_fact_extraction": True,
        "batch_deferred_persist": True,
    }

    try:
        from modules.config import get_cached_config, get_yaml_config

        cfg = get_cached_config()
        defaults["data_dir"] = cfg.memory_data_dir

        yaml_cfg = get_yaml_config()
        ms_cfg = yaml_cfg.get("memory_service", {}) if isinstance(yaml_cfg, dict) else {}
        if isinstance(ms_cfg, dict):
            defaults["wal_path"] = str(ms_cfg.get("wal_path", "") or "").strip()
            defaults["batch_disable_fact_extraction"] = bool(ms_cfg.get("batch_disable_fact_extraction", True))
            defaults["batch_deferred_persist"] = bool(ms_cfg.get("batch_deferred_persist", True))
    except Exception:
        pass

    return {
        "data_dir": os.environ.get("MEMORY_DATA_DIR", str(defaults["data_dir"])),
        "wal_path": (os.environ.get("MEMORY_WAL_PATH", str(defaults["wal_path"])) or "").strip(),
        "batch_disable_fact_extraction": defaults["batch_disable_fact_extraction"],
        "batch_deferred_persist": defaults["batch_deferred_persist"],
    }


_MEMORY_RUNTIME_SETTINGS = _load_memory_runtime_settings()


def _resolve_memory_data_dir() -> str:
    return str(_MEMORY_RUNTIME_SETTINGS.get("data_dir") or _default_memory_data_dir())


class MemoryWAL:
    """Lightweight append-only WAL for store requests and crash recovery."""

    def __init__(self, wal_path: str):
        self._wal_path = wal_path
        self._lock = threading.Lock()
        self._pending_records: dict[str, dict] = {}
        self._next_version_by_user: dict[str, int] = defaultdict(int)
        self._committed_version_by_user: dict[str, int] = defaultdict(int)

        os.makedirs(os.path.dirname(self._wal_path), exist_ok=True)
        if not os.path.exists(self._wal_path):
            with open(self._wal_path, "a", encoding="utf-8"):
                pass

        self._rebuild_state_from_disk()

    def _append_event(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with open(self._wal_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _rebuild_state_from_disk(self) -> None:
        pending: dict[str, dict] = {}
        next_version: dict[str, int] = defaultdict(int)
        committed: dict[str, int] = defaultdict(int)

        with open(self._wal_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue

                event_type = str(event.get("event") or "").strip().lower()
                if event_type == "prepare":
                    record = event.get("record")
                    if not isinstance(record, dict):
                        continue
                    wal_id = str(record.get("wal_id") or "").strip()
                    if not wal_id:
                        continue
                    user_id = _normalize_user_id(record.get("user_id") or "local-user")
                    version = int(record.get("version") or 0)
                    next_version[user_id] = max(int(next_version.get(user_id, 0)), version)
                    pending[wal_id] = {
                        **record,
                        "user_id": user_id,
                        "version": version,
                    }
                elif event_type == "commit":
                    wal_id = str(event.get("wal_id") or "").strip()
                    if not wal_id:
                        continue
                    record = pending.pop(wal_id, None)
                    if not record:
                        continue
                    user_id = _normalize_user_id(record.get("user_id") or "local-user")
                    version = int(record.get("version") or 0)
                    committed[user_id] = max(int(committed.get(user_id, 0)), version)

        self._pending_records = pending
        self._next_version_by_user = defaultdict(int, next_version)
        self._committed_version_by_user = defaultdict(int, committed)

    def prepare_store(self, user_id: str, content: str) -> tuple[str, int]:
        normalized_user = _normalize_user_id(user_id)
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return "", int(self._committed_version_by_user.get(normalized_user, 0))

        with self._lock:
            version = int(self._next_version_by_user.get(normalized_user, 0)) + 1
            self._next_version_by_user[normalized_user] = version
            wal_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"
            record = {
                "wal_id": wal_id,
                "user_id": normalized_user,
                "content": normalized_content,
                "version": version,
                "ts": time.time(),
            }
            self._pending_records[wal_id] = record
            self._append_event({"event": "prepare", "record": record})
            return wal_id, version

    def commit_store(self, wal_id: str) -> None:
        normalized_wal_id = str(wal_id or "").strip()
        if not normalized_wal_id:
            return

        with self._lock:
            record = self._pending_records.pop(normalized_wal_id, None)
            if record is not None:
                user_id = _normalize_user_id(record.get("user_id") or "local-user")
                version = int(record.get("version") or 0)
                self._committed_version_by_user[user_id] = max(
                    int(self._committed_version_by_user.get(user_id, 0)),
                    version,
                )
            self._append_event({"event": "commit", "wal_id": normalized_wal_id, "ts": time.time()})

    def pending_records_snapshot(self) -> list[dict]:
        with self._lock:
            records = list(self._pending_records.values())
        records.sort(key=lambda item: (str(item.get("user_id") or ""), int(item.get("version") or 0)))
        return records

    def committed_version(self, user_id: str) -> int:
        normalized_user = _normalize_user_id(user_id)
        with self._lock:
            return int(self._committed_version_by_user.get(normalized_user, 0))


_wal: MemoryWAL | None = None
_wal_lock = threading.Lock()
_wal_replay_done = False

_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _get_user_lock(user_id: str) -> threading.Lock:
    key = _normalize_user_id(user_id)
    with _user_locks_guard:
        lock = _user_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _user_locks[key] = lock
        return lock


def _get_wal() -> MemoryWAL:
    global _wal
    with _wal_lock:
        if _wal is None:
            configured_wal_path = str(_MEMORY_RUNTIME_SETTINGS.get("wal_path") or "").strip()
            wal_path = configured_wal_path or os.path.join(_resolve_memory_data_dir(), "memory_service_wal.jsonl")
            _wal = MemoryWAL(wal_path)
        return _wal


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_BATCH_DISABLE_FACT_EXTRACTION = _read_bool_env(
    "MEMORY_BATCH_DISABLE_FACT_EXTRACTION",
    bool(_MEMORY_RUNTIME_SETTINGS.get("batch_disable_fact_extraction", True)),
)
_BATCH_DEFERRED_PERSIST = _read_bool_env(
    "MEMORY_BATCH_DEFERRED_PERSIST",
    bool(_MEMORY_RUNTIME_SETTINGS.get("batch_deferred_persist", True)),
)


def _get_cached_engine() -> HumanMemoryEngine | None:
    return getattr(app.state, "memory_engine", None)


def _set_cached_engine(engine: HumanMemoryEngine | None) -> None:
    global _engine
    app.state.memory_engine = engine
    _engine = engine


def reset_engine_for_tests() -> None:
    """Reset cached engine for isolated test scenarios."""
    global _wal_replay_done
    with _engine_lock:
        engine = _get_cached_engine() or _engine
        _set_cached_engine(None)
    _wal_replay_done = False
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
            from modules.config import get_cached_config
            cfg = get_cached_config()
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
                base_dir=_resolve_memory_data_dir(),
                llm_extract_fn=llm_extract_fn,
            )
            _set_cached_engine(engine)
        return engine


def _store_with_wal(
    eng: HumanMemoryEngine,
    content: str,
    user_id: str,
    *,
    disable_fact_extraction: Optional[bool] = None,
    deferred_persist: Optional[bool] = None,
    source: str = "store",
) -> dict:
    wal = _get_wal()
    normalized_content = str(content or "").strip()
    normalized_user = _normalize_user_id(user_id)
    if not normalized_content:
        return {
            "status": "skipped",
            "version": wal.committed_version(normalized_user),
            "wal_id": "",
        }

    wal_id, version = wal.prepare_store(normalized_user, normalized_content)
    metadata = {
        "user_id": normalized_user,
        "version_stamp": version,
        "wal_id": wal_id,
        "source": source,
    }
    if disable_fact_extraction is not None:
        metadata["disable_fact_extraction"] = bool(disable_fact_extraction)
    if deferred_persist is not None:
        metadata["deferred_persist"] = bool(deferred_persist)

    try:
        status = eng.store(normalized_content, metadata=metadata)
        wal.commit_store(wal_id)
        return {
            "status": status or "stored",
            "version": version,
            "wal_id": wal_id,
        }
    except Exception as exc:
        logger.error("[WAL] 存储异常 user=%s wal_id=%s err=%s", normalized_user, wal_id, exc)
        return {
            "status": "error",
            "detail": str(exc),
            "version": wal.committed_version(normalized_user),
            "wal_id": wal_id,
        }


def _replay_pending_wal_records() -> dict[str, int]:
    global _wal_replay_done
    if _wal_replay_done:
        return {"replayed": 0, "failed": 0}

    wal = _get_wal()
    eng = _get_engine()
    pending = wal.pending_records_snapshot()
    replayed = 0
    failed = 0

    for record in pending:
        wal_id = str(record.get("wal_id") or "").strip()
        content = str(record.get("content") or "").strip()
        user_id = _normalize_user_id(record.get("user_id") or "local-user")
        version = int(record.get("version") or 0)
        if not wal_id or not content:
            continue
        try:
            eng.store(
                content,
                metadata={
                    "user_id": user_id,
                    "version_stamp": version,
                    "wal_id": wal_id,
                    "source": "wal-replay",
                    "disable_fact_extraction": _BATCH_DISABLE_FACT_EXTRACTION,
                    "deferred_persist": _BATCH_DEFERRED_PERSIST,
                },
            )
            wal.commit_store(wal_id)
            replayed += 1
        except Exception as exc:
            failed += 1
            logger.error("[WAL] replay failed user=%s wal_id=%s err=%s", user_id, wal_id, exc)

    _wal_replay_done = True
    return {"replayed": replayed, "failed": failed}


app = FastAPI(title="Memory Service (MemPalace)", version="3.0.0")


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
    replay_result = await asyncio.to_thread(_replay_pending_wal_records)
    if replay_result.get("replayed", 0) > 0 or replay_result.get("failed", 0) > 0:
        logger.info(
            "[WAL] replay complete replayed=%s failed=%s",
            replay_result.get("replayed", 0),
            replay_result.get("failed", 0),
        )
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
    wal = _get_wal()
    user_id = _normalize_user_id(req.user_id)
    result: dict = {
        "context": "",
        "retrieve_status": "ok",
        "store_status": "skipped",
        "context_version": wal.committed_version(user_id),
    }

    # 保证同一 user_id 的写入版本和读取上下文具备因果一致性。
    user_lock = _get_user_lock(user_id)
    with user_lock:
        # Store first (pending content from previous turn)
        if req.store_content and req.store_content.strip():
            store_result = _store_with_wal(
                eng,
                req.store_content,
                user_id,
                disable_fact_extraction=_BATCH_DISABLE_FACT_EXTRACTION,
                deferred_persist=_BATCH_DEFERRED_PERSIST,
                source="batch",
            )
            result["store_status"] = str(store_result.get("status") or "error")
            result["context_version"] = int(store_result.get("version") or wal.committed_version(user_id))
            if result["store_status"] != "error":
                logger.info(f"[batch] 已写入 WAL+存储 ({len(req.store_content)} chars)")

        # Retrieve
        if req.retrieve and req.query:
            try:
                ctx = eng.retrieve(query=req.query, n_results=req.n_results, user_id=user_id)
                result["context"] = ctx or ""
            except Exception as e:
                logger.error(f"[检索异常] {e}")
                result["retrieve_status"] = "failed"
                result["context"] = ""

        result["context_version"] = wal.committed_version(user_id)

    return result


@app.post("/batch")
async def batch(req: BatchRequest):
    """
    Combined store + retrieve endpoint used by Orchestrator.

    Orchestrator sends:
      - store_content: pending interaction from previous turn (if any)
      - query: current query for retrieval

    Returns dict with 'context' string and status fields.
    Persistence follows MemPalace deferred/immediate policy configured in engine.
    """
    return await asyncio.to_thread(_batch_sync, req)


def _store_sync(content: str, user_id: str) -> dict:
    """Store sync worker."""
    eng = _get_engine()
    normalized_user = _normalize_user_id(user_id)
    user_lock = _get_user_lock(normalized_user)
    with user_lock:
        result = _store_with_wal(
            eng,
            content or "",
            normalized_user,
            source="store",
        )
    return {
        "status": result.get("status", "error"),
        "version": int(result.get("version") or _get_wal().committed_version(normalized_user)),
        "wal_id": str(result.get("wal_id") or ""),
        **({"detail": result.get("detail")} if result.get("detail") else {}),
    }


@app.post("/store")
async def do_store(content: str = Body(...), user_id: str = "local-user") -> dict[str, Any]:
    """Explicit store endpoint."""
    return await asyncio.to_thread(_store_sync, content, user_id)


def _stats_sync() -> dict:
    """Stats sync worker."""
    eng = _get_engine()
    data = eng.stats()
    if isinstance(data, dict):
        return dict(data)
    return {"data": data}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    """Return memory statistics."""
    return await asyncio.to_thread(_stats_sync)


def _close_sync() -> dict:
    """Close sync worker."""
    global _wal_replay_done
    engine = None
    with _engine_lock:
        engine = _get_cached_engine() or _engine
        _set_cached_engine(None)
    _wal_replay_done = False
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
