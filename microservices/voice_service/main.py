import asyncio
import os
import time
import uuid
import wave
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from starlette.responses import Response

from modules.logging_config import clear_context, get_logger, set_context
from modules.python_runtime_guard import ensure_supported_python_runtime

logger = get_logger("VoiceService")


def _read_bool(raw: str | None, default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _load_voice_runtime_settings() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "wav_output_dir": os.path.join(os.getcwd(), "data", "temp"),
        "wav_cleanup_enabled": True,
        "wav_cleanup_interval_sec": 120.0,
        "wav_ttl_sec": 1800.0,
        "sovits_url": "http://127.0.0.1:9880",
    }

    try:
        from modules.config import get_cached_config, load_tuning

        cfg = get_cached_config()
        vt = load_tuning().voice
        defaults.update(
            {
                "wav_output_dir": vt.wav_output_dir,
                "wav_cleanup_enabled": bool(vt.wav_cleanup_enabled),
                "wav_cleanup_interval_sec": float(vt.wav_cleanup_interval_sec),
                "wav_ttl_sec": float(vt.wav_ttl_sec),
                "sovits_url": cfg.sovits_url,
            }
        )
    except Exception:
        pass

    wav_output_dir = (
        os.getenv("VOICE_WAV_OUTPUT_DIR", str(defaults["wav_output_dir"])) or str(defaults["wav_output_dir"])
    ).strip()
    wav_cleanup_enabled = _read_bool(
        os.getenv("VOICE_WAV_CLEANUP_ENABLED"),
        bool(defaults["wav_cleanup_enabled"]),
    )
    wav_cleanup_interval_sec = max(
        5.0,
        float(
            (
                os.getenv("VOICE_WAV_CLEANUP_INTERVAL_SEC", str(defaults["wav_cleanup_interval_sec"]))
                or defaults["wav_cleanup_interval_sec"]
            )
        ),
    )
    wav_ttl_sec = max(
        30.0,
        float((os.getenv("VOICE_WAV_TTL_SEC", str(defaults["wav_ttl_sec"])) or defaults["wav_ttl_sec"])),
    )
    sovits_url = (os.getenv("SOVITS_URL", str(defaults["sovits_url"])) or str(defaults["sovits_url"])).strip()

    return {
        "wav_output_dir": wav_output_dir,
        "wav_cleanup_enabled": wav_cleanup_enabled,
        "wav_cleanup_interval_sec": wav_cleanup_interval_sec,
        "wav_ttl_sec": wav_ttl_sec,
        "sovits_url": sovits_url,
    }


_VOICE_RUNTIME = _load_voice_runtime_settings()
VOICE_WAV_OUTPUT_DIR = str(_VOICE_RUNTIME["wav_output_dir"])
VOICE_WAV_CLEANUP_ENABLED = bool(_VOICE_RUNTIME["wav_cleanup_enabled"])
VOICE_WAV_CLEANUP_INTERVAL_SEC = float(_VOICE_RUNTIME["wav_cleanup_interval_sec"])
VOICE_WAV_TTL_SEC = float(_VOICE_RUNTIME["wav_ttl_sec"])
VOICE_SOVITS_URL = str(_VOICE_RUNTIME["sovits_url"])

_VOICE_INIT_ERROR = ""
_CLEANUP_TASK: asyncio.Task[None] | None = None


class VoiceRuntime(Protocol):
    def close(self) -> None:
        ...

    def get_tts_stats(self) -> dict[str, Any]:
        ...

    def get_provider_status(self) -> dict[str, Any]:
        ...

    def speak_and_save(self, text: str, output_path: str) -> bool:
        ...


_VOICE_MANAGER: VoiceRuntime | None = None


def _ensure_wav_output_dir() -> str:
    output_dir = Path(VOICE_WAV_OUTPUT_DIR).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def _build_wav_output_path() -> str:
    output_dir = _ensure_wav_output_dir()
    filename = f"tts_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.wav"
    return str(Path(output_dir) / filename)


def _cleanup_stale_wavs_once() -> int:
    output_dir = Path(_ensure_wav_output_dir())
    now = time.time()
    deleted = 0

    for wav_path in output_dir.glob("tts_*.wav"):
        try:
            age = now - float(wav_path.stat().st_mtime)
            if age >= VOICE_WAV_TTL_SEC:
                wav_path.unlink(missing_ok=True)
                deleted += 1
        except Exception:
            continue

    return deleted


async def _wav_cleanup_loop() -> None:
    while True:
        try:
            deleted = await asyncio.to_thread(_cleanup_stale_wavs_once)
            if deleted > 0:
                logger.info(f"[WAV Cleanup] deleted={deleted}")
            await asyncio.sleep(VOICE_WAV_CLEANUP_INTERVAL_SEC)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"[WAV Cleanup] loop error: {exc}")
            await asyncio.sleep(VOICE_WAV_CLEANUP_INTERVAL_SEC)


def _read_wav_meta(wav_path: str) -> dict:
    with wave.open(wav_path, "rb") as wav_file:
        n_frames = int(wav_file.getnframes() or 0)
        sample_rate = int(wav_file.getframerate() or 0)
        duration_sec = float(n_frames) / float(sample_rate) if sample_rate > 0 else 0.0
        return {
            "sample_rate": sample_rate,
            "channels": int(wav_file.getnchannels() or 1),
            "duration_sec": round(duration_sec, 4),
        }


def _try_init_voice() -> None:
    global _VOICE_MANAGER
    global _VOICE_INIT_ERROR

    try:
        from modules.config import get_cached_config
        from modules.voice import VoiceManager

        cfg = get_cached_config()
        _VOICE_MANAGER = VoiceManager(
            sovits_url=VOICE_SOVITS_URL or cfg.sovits_url,
            ref_audio=cfg.ref_audio,
            prompt_text=cfg.prompt_text,
        )
        _VOICE_INIT_ERROR = ""
    except Exception as exc:
        _VOICE_MANAGER = None
        _VOICE_INIT_ERROR = str(exc)


@asynccontextmanager
async def lifespan(app):
    global _CLEANUP_TASK

    from modules.utils import ensure_local_no_proxy_env

    ensure_local_no_proxy_env()
    ensure_supported_python_runtime(logger=logger)
    await asyncio.to_thread(_ensure_wav_output_dir)
    await asyncio.to_thread(_try_init_voice)

    if VOICE_WAV_CLEANUP_ENABLED and _CLEANUP_TASK is None:
        _CLEANUP_TASK = asyncio.create_task(_wav_cleanup_loop())
        logger.info(
            "[WAV Cleanup] enabled interval=%ss ttl=%ss dir=%s",
            int(VOICE_WAV_CLEANUP_INTERVAL_SEC),
            int(VOICE_WAV_TTL_SEC),
            _ensure_wav_output_dir(),
        )
    yield

    if _CLEANUP_TASK is not None:
        _CLEANUP_TASK.cancel()
        try:
            await _CLEANUP_TASK
        except asyncio.CancelledError:
            pass
        _CLEANUP_TASK = None

    if _VOICE_MANAGER is not None:
        await asyncio.to_thread(_VOICE_MANAGER.close)


app = FastAPI(title="project-local-voice-service", version="0.1.0", lifespan=lifespan)


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


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = Field(default="default")


@app.get("/health/live")
async def health_live() -> dict:
    """轻量就绪探针：不访问 SoVITS，供 start.bat / 编排器判断进程已可接受连接。"""
    return {
        "status": "ok",
        "service": "voice-service",
        "voice_manager_ready": _VOICE_MANAGER is not None,
    }


@app.get("/health")
async def health() -> dict:
    if _VOICE_MANAGER is None:
        return {
            "status": "degraded",
            "service": "voice-service",
            "mode": "fallback-no-audio",
            "error": _VOICE_INIT_ERROR,
        }

    stats = await asyncio.to_thread(_VOICE_MANAGER.get_tts_stats)
    provider = await asyncio.to_thread(_VOICE_MANAGER.get_provider_status)
    state = "ok" if (provider.get("sovits_reachable") or provider.get("system_tts_fallback_enabled")) else "degraded"
    return {
        "status": state,
        "service": "voice-service",
        "mode": "real-voice-manager",
        "error": "",
        "stats": stats,
        "provider": provider,
    }


@app.post("/speak")
async def speak(request: SpeakRequest) -> dict:
    if _VOICE_MANAGER is not None:
        # 并行执行 provider 检查和 wav 路径生成（消除串行等待）
        provider, wav_path = await asyncio.gather(
            asyncio.to_thread(_VOICE_MANAGER.get_provider_status),
            asyncio.to_thread(_build_wav_output_path),
        )

        success = await asyncio.to_thread(_VOICE_MANAGER.speak_and_save, request.text, wav_path)

        if not success:
            fallback_ok = await asyncio.to_thread(_VOICE_MANAGER.save_system_tts_wav, request.text, wav_path)
            if fallback_ok:
                logger.info("SoVITS 合成失败，已切换系统 TTS wav 兜底")
                wav_meta = await asyncio.to_thread(_read_wav_meta, wav_path)
                return {
                    "status": "ready",
                    "voice": request.voice,
                    "preview": request.text[:80],
                    "mode": "wav-ready-system-tts",
                    "wav_path": wav_path,
                    **wav_meta,
                }

            try:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass
            return {
                "status": "failed",
                "voice": request.voice,
                "preview": request.text[:80],
                "mode": "tts-failed",
                "wav_path": "",
                "reason": "speak_and_save_failed",
            }

        # 验证文件确实存在且可读，防止竞态删除或写入失败
        if not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 100:
            logger.warning("TTS 报告成功但文件不存在或过小: %s", wav_path)
            return {
                "status": "failed",
                "voice": request.voice,
                "preview": request.text[:80],
                "mode": "tts-failed",
                "wav_path": "",
                "reason": "wav_file_missing_after_write",
            }

        wav_meta = await asyncio.to_thread(_read_wav_meta, wav_path)
        mode = "wav-ready"
        if not provider.get("sovits_reachable", False):
            mode = "wav-ready-degraded-provider"

        return {
            "status": "ready",
            "voice": request.voice,
            "preview": request.text[:80],
            "mode": mode,
            "wav_path": wav_path,
            **wav_meta,
        }

    return {
        "status": "failed",
        "voice": request.voice,
        "preview": request.text[:80],
        "mode": "fallback-no-audio",
        "wav_path": "",
        "reason": "voice_manager_unavailable",
    }
