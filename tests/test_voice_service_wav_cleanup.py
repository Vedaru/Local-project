import importlib
import os
import time
from pathlib import Path

import pytest

import microservices.voice_service.main as voice_service_main


@pytest.mark.unit
def test_voice_service_default_wav_output_uses_data_temp(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VOICE_WAV_OUTPUT_DIR", raising=False)
    module = importlib.reload(voice_service_main)

    normalized = Path(module.VOICE_WAV_OUTPUT_DIR).as_posix().lower()
    assert normalized.rstrip("/").endswith("data/temp")


@pytest.mark.unit
def test_cleanup_stale_wavs_removes_expired_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_WAV_OUTPUT_DIR", str(tmp_path))
    module = importlib.reload(voice_service_main)

    old_wav = tmp_path / "tts_old.wav"
    new_wav = tmp_path / "tts_new.wav"
    old_wav.write_bytes(b"RIFF")
    new_wav.write_bytes(b"RIFF")

    now = time.time()
    os.utime(old_wav, (now - 600, now - 600))
    os.utime(new_wav, (now, now))

    monkeypatch.setattr(module, "VOICE_WAV_TTL_SEC", 120.0)

    deleted = module._cleanup_stale_wavs_once()

    assert deleted == 1
    assert not old_wav.exists()
    assert new_wav.exists()
