"""Unit tests for TTS temp wav cleanup in AudioPlaybackController."""

from pathlib import Path

import pytest

from modules.application.audio_playback_controller import AudioPlaybackController


@pytest.mark.unit
def test_collect_wav_paths_deduplicates_segment_and_top_level(tmp_path: Path):
    wav_a = tmp_path / "tts_a.wav"
    wav_b = tmp_path / "tts_b.wav"
    wav_a.write_bytes(b"RIFF")
    wav_b.write_bytes(b"RIFF")

    payload = {
        "wav_path": str(wav_a),
        "segments": [
            {"index": 0, "wav_path": str(wav_a)},
            {"index": 1, "wav_path": str(wav_b)},
        ],
    }

    paths = AudioPlaybackController._collect_wav_paths(payload)

    assert paths == [str(wav_a.resolve()), str(wav_b.resolve())]


@pytest.mark.unit
def test_delete_wav_file_removes_existing_file(tmp_path: Path):
    wav_file = tmp_path / "tts_delete.wav"
    wav_file.write_bytes(b"RIFF")

    assert AudioPlaybackController._delete_wav_file(str(wav_file)) is True
    assert not wav_file.exists()
