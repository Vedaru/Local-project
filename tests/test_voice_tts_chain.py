import queue
import threading
from collections import deque

import pytest

from modules.voice import VoiceManager


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
    manager.stop_current = threading.Event()
    manager.is_playing = False
    manager.sample_rate = 32000
    return manager


def _drain_queue_items(q: queue.Queue):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


@pytest.mark.unit
def test_tts_worker_direct_mode_skips_buffered_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(VoiceManager.TTS_BUFFERED_FALLBACK_ENV, "0")
    manager = _build_voice_manager_for_unit_test()

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
    monkeypatch.setenv(VoiceManager.TTS_BUFFERED_FALLBACK_ENV, "1")
    manager = _build_voice_manager_for_unit_test()

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
    assert any(
        chunk not in (VoiceManager._STREAM_START, VoiceManager._STREAM_END)
        for chunk in audio_items
    )

    cache_key = manager._cache_key("启用回退")
    assert manager._audio_cache.get(cache_key) == fallback_audio


@pytest.mark.unit
def test_tts_stats_can_reset_and_report_switch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(VoiceManager.TTS_BUFFERED_FALLBACK_ENV, "true")
    manager = _build_voice_manager_for_unit_test()

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
