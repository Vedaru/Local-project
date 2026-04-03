import asyncio
import os
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="project-local-voice-service", version="0.1.0")

_VOICE_MANAGER: Optional[object] = None
_VOICE_INIT_ERROR = ""


def _try_init_voice() -> None:
    global _VOICE_MANAGER
    global _VOICE_INIT_ERROR

    try:
        from modules.config import load_config
        from modules.voice import VoiceManager

        cfg = load_config()
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
    await asyncio.to_thread(_try_init_voice)


@app.on_event("shutdown")
async def shutdown_event() -> None:
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
        await asyncio.to_thread(_VOICE_MANAGER.speak, request.text)
        mode = "real-voice-manager"
        if not provider.get("sovits_reachable", False) and provider.get("system_tts_fallback_enabled", False):
            mode = "system-tts-fallback"
        return {
            "status": "queued",
            "voice": request.voice,
            "preview": request.text[:80],
            "mode": mode,
        }

    return {
        "status": "queued",
        "voice": request.voice,
        "preview": request.text[:80],
        "mode": "fallback-no-audio",
    }
