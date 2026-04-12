import asyncio
import os
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI
from pydantic import BaseModel, Field

from modules.logging_config import get_logger
from modules.python_runtime_guard import ensure_supported_python_runtime

app = FastAPI(title="project-local-voice-service", version="0.1.0")

logger = get_logger("VoiceService")

VOICE_WAV_OUTPUT_DIR = os.getenv("VOICE_WAV_OUTPUT_DIR", os.path.join(os.getcwd(), "data", "temp"))
VOICE_WAV_CLEANUP_ENABLED = (os.getenv("VOICE_WAV_CLEANUP_ENABLED", "1") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
VOICE_WAV_CLEANUP_INTERVAL_SEC = max(5.0, float(os.getenv("VOICE_WAV_CLEANUP_INTERVAL_SEC", "120") or "120"))
VOICE_WAV_TTL_SEC = max(30.0, float(os.getenv("VOICE_WAV_TTL_SEC", "1800") or "1800"))

_VOICE_INIT_ERROR = ""
_CLEANUP_TASK: asyncio.Task[None] | None = None


class VoiceRuntime(Protocol):
    def close(self) -> None: ...
    def get_tts_stats(self) -> dict[str, Any]: ...
    def get_provider_status(self) -> dict[str, Any]: ...
    def speak_and_save(self, text: str, output_path: str) -> bool: ...


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
            sovits_url=os.getenv("SOVITS_URL", cfg.sovits_url),
            ref_audio=cfg.ref_audio,
            prompt_text=cfg.prompt_text,
        )
        _VOICE_INIT_ERROR = ""
    except Exception as exc:
        _VOICE_MANAGER = None
        _VOICE_INIT_ERROR = str(exc)


@app.on_event("startup")
async def startup_event() -> None:
    global _CLEANUP_TASK

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


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _CLEANUP_TASK

    if _CLEANUP_TASK is not None:
        _CLEANUP_TASK.cancel()
        try:
            await _CLEANUP_TASK
        except asyncio.CancelledError:
            pass
        _CLEANUP_TASK = None

    if _VOICE_MANAGER is not None:
        await asyncio.to_thread(_VOICE_MANAGER.close)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = Field(default="default")


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
        provider = await asyncio.to_thread(_VOICE_MANAGER.get_provider_status)
        wav_path = await asyncio.to_thread(_build_wav_output_path)
        success = await asyncio.to_thread(_VOICE_MANAGER.speak_and_save, request.text, wav_path)

        if not success:
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
