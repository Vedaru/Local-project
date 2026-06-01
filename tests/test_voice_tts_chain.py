import queue
import threading
from collections import deque
from pathlib import Path

import pytest

from modules.voice import VoiceManager


class _FakeVoiceCppBackend:
    def __init__(
        self,
        *,
        wav_success: bool = True,
        volume: float | None = None,
        chunk_index: list[tuple[int, int]] | None = None,
    ) -> None:
        self.wav_success = wav_success
        self.volume = volume
        self.chunk_index = chunk_index
        self.save_calls = 0
        self.volume_calls = 0
        self.batch_volume_calls = 0
        self.chunk_index_calls = 0

    def save_pcm_mono16(self, wav_path: str, pcm_data: bytes, sample_rate: int) -> bool:
        self.save_calls += 1
        if self.wav_success:
            with open(wav_path, "wb") as output_file:
                output_file.write(b"FAKEWAV")
        return self.wav_success

    def compute_volume_from_pcm16(
        self, pcm_chunk: bytes, *, gate: float, normalizer: float, power: float
    ) -> float | None:
        self.volume_calls += 1
        _ = (pcm_chunk, gate, normalizer, power)
        return self.volume

    def compute_volume_batch_from_pcm16(
        self,
        pcm_chunk: bytes,
        *,
        frame_samples: int,
        gate: float,
        normalizer: float,
        power: float,
    ) -> list[float] | None:
        self.batch_volume_calls += 1
        _ = (gate, normalizer, power)
        if self.volume is None:
            return None
        if int(frame_samples or 0) <= 0:
            return []
        frame_count = (len(pcm_chunk) // 2) // int(frame_samples)
        if frame_count <= 0:
            return []
        return [float(self.volume)] * frame_count

    def build_chunk_index(self, total_size: int, chunk_size: int) -> list[tuple[int, int]] | None:
        self.chunk_index_calls += 1
        _ = (total_size, chunk_size)
        if self.chunk_index is None:
            return None
        return list(self.chunk_index)


def _build_voice_manager_for_unit_test() -> VoiceManager:
    manager = VoiceManager.__new__(VoiceManager)
    manager.sovits_url = "http://127.0.0.1:9880"
    manager.ref_audio = "dummy.wav"
    manager.prompt_text = ""
    manager.text_queue = queue.Queue()
    manager.audio_queue = queue.Queue()
    manager.session = object()
    manager._audio_cache = {}
    manager._audio_cache_order = deque()
    manager._audio_cache_capacity = 24
    manager._audio_cache_lock = threading.Lock()
    manager._tts_stats_lock = threading.Lock()
    manager._tts_stats = manager._initial_tts_stats()
    manager._ref_audio_missing = False
    manager._voice_cpp_backend = None
    manager.system_tts_enabled = True
    manager.stop_current = threading.Event()
    manager.is_playing = False
    manager.sample_rate = 32000
    manager.connect_timeout_sec = 5
    manager.read_timeout_sec = 30
    return manager


def _drain_queue_items(q: queue.Queue):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


@pytest.mark.unit
def test_tts_worker_direct_mode_skips_buffered_fallback(monkeypatch: pytest.MonkeyPatch):
    manager = _build_voice_manager_for_unit_test()
    manager.system_tts_enabled = False

    monkeypatch.setattr(
        manager,
        "_stream_tts_to_queue",
        lambda _text, *, connect_timeout, read_timeout: ("empty", b""),
    )
    monkeypatch.setattr(
        manager,
        "_request_tts_audio",
        lambda _text, *, connect_timeout, read_timeout: (_ for _ in ()).throw(
            AssertionError("buffered fallback should be disabled in direct mode")
        ),
    )

    manager.text_queue.put("测试收口模式")
    manager.text_queue.put(None)
    manager.tts_worker()

    stats = manager.get_tts_stats()
    audio_items = _drain_queue_items(manager.audio_queue)

    assert stats["stream_attempts"] == 1
    assert stats["stream_empty"] == 1
    assert stats["fallback_skipped_direct_mode"] == 1
    assert stats["buffered_fallback_attempts"] == 0
    assert VoiceManager._STREAM_START not in audio_items
    assert audio_items.count(VoiceManager._STREAM_END) == 1


@pytest.mark.unit
def test_tts_worker_uses_buffered_fallback_when_enabled(monkeypatch: pytest.MonkeyPatch):
    manager = _build_voice_manager_for_unit_test()
    manager.system_tts_enabled = True

    fallback_audio = b"12345678" * 256

    monkeypatch.setattr(
        manager,
        "_stream_tts_to_queue",
        lambda _text, *, connect_timeout, read_timeout: ("empty", b""),
    )
    monkeypatch.setattr(
        manager,
        "_request_tts_audio",
        lambda _text, *, connect_timeout, read_timeout: fallback_audio,
    )

    manager.text_queue.put("启用回退")
    manager.text_queue.put(None)
    manager.tts_worker()

    stats = manager.get_tts_stats()
    audio_items = _drain_queue_items(manager.audio_queue)

    assert stats["stream_attempts"] == 1
    assert stats["buffered_fallback_attempts"] == 1
    assert stats["buffered_fallback_success"] == 1
    assert stats["fallback_skipped_direct_mode"] == 0

    assert audio_items[0] == VoiceManager._STREAM_START
    assert audio_items[-1] == VoiceManager._STREAM_END
    assert any(chunk not in (VoiceManager._STREAM_START, VoiceManager._STREAM_END) for chunk in audio_items)

    cache_key = manager._cache_key("启用回退")
    assert manager._audio_cache.get(cache_key) == fallback_audio


@pytest.mark.unit
def test_tts_stats_can_reset_and_report_switch(monkeypatch: pytest.MonkeyPatch):
    _ = monkeypatch
    manager = _build_voice_manager_for_unit_test()
    manager.system_tts_enabled = True

    manager._increment_tts_stat("stream_attempts")
    manager._increment_tts_stat("stream_errors")

    before = manager.get_tts_stats()
    assert before["stream_attempts"] == 1
    assert before["stream_errors"] == 1
    assert before["buffered_fallback_enabled"] is True

    manager.reset_tts_stats()
    after = manager.get_tts_stats()

    assert after["stream_attempts"] == 0
    assert after["stream_errors"] == 0
    assert after["buffered_fallback_enabled"] is True


@pytest.mark.unit
def test_speak_and_save_prefers_cpp_wav_acceleration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(wav_success=True)
    manager._voice_cpp_backend = backend

    pcm_data = b"\x01\x00" * 1600
    monkeypatch.setattr(
        manager,
        "_request_tts_audio",
        lambda _text, *, connect_timeout, read_timeout: pcm_data,
    )

    wav_path = tmp_path / "voice_cpp_accel.wav"
    success = manager.speak_and_save("测试C++加速", str(wav_path))

    assert success is True
    assert backend.save_calls == 1
    assert wav_path.exists()

    stats = manager.get_tts_stats()
    assert stats["cpp_wav_accel_success"] == 1
    assert stats["cpp_wav_accel_errors"] == 0


@pytest.mark.unit
def test_speak_and_save_fallbacks_to_python_when_cpp_wav_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(wav_success=False)
    manager._voice_cpp_backend = backend

    pcm_data = b"\x02\x00" * 800
    monkeypatch.setattr(
        manager,
        "_request_tts_audio",
        lambda _text, *, connect_timeout, read_timeout: pcm_data,
    )

    wav_path = tmp_path / "voice_cpp_failure.wav"
    success = manager.speak_and_save("测试回退", str(wav_path))

    assert success is True
    assert backend.save_calls == 1
    assert wav_path.exists()
    assert wav_path.read_bytes().startswith(b"RIFF")

    stats = manager.get_tts_stats()
    assert stats["cpp_wav_accel_success"] == 0
    assert stats["cpp_wav_accel_errors"] == 1
    assert stats["python_wav_fallback_success"] == 1
    assert stats["python_wav_fallback_errors"] == 0


@pytest.mark.unit
def test_speak_and_save_uses_python_writer_when_cpp_backend_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = _build_voice_manager_for_unit_test()
    manager._voice_cpp_backend = None

    pcm_data = b"\x02\x00" * 800
    monkeypatch.setattr(
        manager,
        "_request_tts_audio",
        lambda _text, *, connect_timeout, read_timeout: pcm_data,
    )

    wav_path = tmp_path / "voice_python_fallback.wav"
    success = manager.speak_and_save("测试无C++回退", str(wav_path))

    assert success is True
    assert wav_path.exists()
    assert wav_path.read_bytes().startswith(b"RIFF")

    stats = manager.get_tts_stats()
    assert stats["cpp_wav_accel_success"] == 0
    assert stats["cpp_wav_accel_errors"] == 1
    assert stats["python_wav_fallback_success"] == 1
    assert stats["python_wav_fallback_errors"] == 0


@pytest.mark.unit
def test_compute_lip_volume_uses_cpp_backend():
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(volume=0.42)
    manager._voice_cpp_backend = backend

    volume = manager._compute_lip_volume(b"\x03\x00" * 128)

    assert volume == pytest.approx(0.42)
    assert backend.batch_volume_calls == 1
    assert backend.volume_calls == 0


@pytest.mark.unit
def test_compute_lip_volumes_batch_path_for_multiple_chunks():
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(volume=0.25)
    manager._voice_cpp_backend = backend

    volumes = manager._compute_lip_volumes([b"\x01\x00" * 64, b"\x02\x00" * 64])

    assert volumes == pytest.approx([0.25, 0.25])
    assert backend.batch_volume_calls == 1


@pytest.mark.unit
def test_tts_worker_cached_audio_uses_cpp_chunk_acceleration():
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(chunk_index=[(0, 4), (4, 4)])
    manager._voice_cpp_backend = backend
    manager.system_tts_enabled = False

    manager._set_cached_audio("缓存命中", b"abcdefgh")

    manager.text_queue.put("缓存命中")
    manager.text_queue.put(None)
    manager.tts_worker()

    audio_items = _drain_queue_items(manager.audio_queue)
    data_chunks = [item for item in audio_items if item not in (VoiceManager._STREAM_START, VoiceManager._STREAM_END)]
    stats = manager.get_tts_stats()

    assert data_chunks == [b"abcd", b"efgh"]
    assert backend.chunk_index_calls == 1
    assert stats["cpp_chunk_accel_success"] == 1
    assert stats["cpp_chunk_accel_errors"] == 0


@pytest.mark.unit
def test_tts_worker_cached_audio_chunk_index_fallback_to_python():
    manager = _build_voice_manager_for_unit_test()
    backend = _FakeVoiceCppBackend(chunk_index=None)
    manager._voice_cpp_backend = backend
    manager.system_tts_enabled = False

    manager._set_cached_audio("回退切片", b"123456")

    manager.text_queue.put("回退切片")
    manager.text_queue.put(None)
    manager.tts_worker()

    audio_items = _drain_queue_items(manager.audio_queue)
    data_chunks = [item for item in audio_items if item not in (VoiceManager._STREAM_START, VoiceManager._STREAM_END)]
    stats = manager.get_tts_stats()

    assert data_chunks == [b"123456"]
    assert backend.chunk_index_calls == 1
    assert stats["cpp_chunk_accel_success"] == 0
    assert stats["cpp_chunk_accel_errors"] == 1
