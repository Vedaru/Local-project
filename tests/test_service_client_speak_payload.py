import pytest

from microservices.service_client import MicroserviceAIService, ServiceCallbacks


@pytest.mark.unit
def test_handle_chat_emits_wav_payload(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    service = MicroserviceAIService(
        ServiceCallbacks(
            on_response_ready=lambda _text: None,
            on_expression_change=lambda _value: None,
            on_status_update=lambda _status: None,
            on_speak_request=lambda payload: captured.setdefault("payload", payload),
        )
    )

    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload, timeout: {
            "answer": "测试回复",
            "tts": {
                "status": "ready",
                "mode": "wav-ready",
                "wav_path": "D:/tmp/tts_1.wav",
                "duration_sec": 1.23,
            },
        },
    )

    service._handle_chat("你好")

    payload = captured["payload"]
    assert payload["text"] == "测试回复"
    assert payload["wav_path"] == "D:/tmp/tts_1.wav"
    assert payload["status"] == "ready"
    assert payload["mode"] == "wav-ready"
    assert payload["duration_sec"] == pytest.approx(1.23)


@pytest.mark.unit
def test_handle_chat_emits_text_fallback_payload(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    service = MicroserviceAIService(
        ServiceCallbacks(
            on_response_ready=lambda _text: None,
            on_expression_change=lambda _value: None,
            on_status_update=lambda _status: None,
            on_speak_request=lambda payload: captured.setdefault("payload", payload),
        )
    )

    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload, timeout: {
            "answer": "仅文本回复",
            "tts": {
                "status": "failed",
                "mode": "tts-failed",
            },
        },
    )

    service._handle_chat("你好")

    payload = captured["payload"]
    assert payload["text"] == "仅文本回复"
    assert payload["wav_path"] == ""
    assert payload["status"] == "failed"
    assert payload["mode"] == "tts-failed"
