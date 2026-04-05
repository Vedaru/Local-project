import importlib
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _reload_gateway_module(monkeypatch, gateway_timeout=None, memory_timeout=None, agent_timeout=None, voice_timeout=None):
    if gateway_timeout is None:
        monkeypatch.delenv("GATEWAY_CHAT_TIMEOUT_SEC", raising=False)
    else:
        monkeypatch.setenv("GATEWAY_CHAT_TIMEOUT_SEC", str(gateway_timeout))

    if memory_timeout is None:
        monkeypatch.delenv("ORCH_MEMORY_TIMEOUT_SEC", raising=False)
    else:
        monkeypatch.setenv("ORCH_MEMORY_TIMEOUT_SEC", str(memory_timeout))

    if agent_timeout is None:
        monkeypatch.delenv("ORCH_AGENT_TIMEOUT_SEC", raising=False)
    else:
        monkeypatch.setenv("ORCH_AGENT_TIMEOUT_SEC", str(agent_timeout))

    if voice_timeout is None:
        monkeypatch.delenv("ORCH_VOICE_TIMEOUT_SEC", raising=False)
    else:
        monkeypatch.setenv("ORCH_VOICE_TIMEOUT_SEC", str(voice_timeout))

    import microservices.gateway.main as gateway_main

    return importlib.reload(gateway_main)


def _reload_orchestrator_module(monkeypatch):
    import microservices.orchestrator.main as orchestrator_main

    return importlib.reload(orchestrator_main)


def test_gateway_chat_uses_configured_timeout(monkeypatch):
    gateway = _reload_gateway_module(monkeypatch, gateway_timeout=77)
    captured = {}

    async def fake_post_json(url, payload, timeout, headers=None):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["payload"] = payload
        captured["headers"] = headers or {}
        return {"answer": "ok", "tts": {}}

    monkeypatch.setattr(gateway, "post_json", fake_post_json)

    client = TestClient(gateway.app)
    response = client.post(
        "/v1/chat",
        json={
            "query": "hello",
            "user_id": "u1",
            "route_to_agent": False,
        },
    )

    assert response.status_code == 200
    assert captured["url"].endswith("/chat")
    assert captured["timeout"] == 77.0


def test_gateway_chat_timeout_default_follows_orchestrator_env(monkeypatch):
    gateway = _reload_gateway_module(
        monkeypatch,
        gateway_timeout=None,
        memory_timeout=5,
        agent_timeout=100,
        voice_timeout=20,
    )

    # 公式: MEMORY + max(AGENT, VOICE) = 5 + max(100, 20) = 105.0
    assert gateway.GATEWAY_CHAT_TIMEOUT_SEC == 105.0


def test_orchestrator_memory_timeout_degrades_instead_of_502(monkeypatch):
    orchestrator = _reload_orchestrator_module(monkeypatch)

    async def fake_post_json(url, payload, timeout, headers=None):
        if url.endswith("/batch"):
            raise TimeoutError("memory batch timeout")
        if url.endswith("/speak"):
            return {"status": "ok", "mode": "tts", "wav_path": ""}
        raise AssertionError(f"unexpected url: {url}")

    class _Decision:
        should_trigger = False
        reason = ""

    monkeypatch.setattr(orchestrator, "post_json", fake_post_json)
    monkeypatch.setattr(orchestrator, "call_llm", lambda *_args, **_kwargs: "mock-answer")
    monkeypatch.setattr(orchestrator, "decide_agent_routing", lambda **_kwargs: _Decision())
    monkeypatch.setattr(
        orchestrator,
        "load_config",
        lambda: SimpleNamespace(system_prompt="", model_name="mock-model"),
    )

    client = TestClient(orchestrator.app)
    response = client.post(
        "/chat",
        json={
            "query": "hello",
            "user_id": "u1",
            "route_to_agent": False,
            "force_chat_only": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "mock-answer"
    assert payload["memory_context"] == ""
    assert payload["memory_retrieve_status"] == "fallback-empty"
    assert payload["memory_store_status"] == "deferred"
    assert payload["memory_store_flush_status"] == "skipped"


def test_orchestrator_memory_batch_flushes_previous_turn(monkeypatch):
    orchestrator = _reload_orchestrator_module(monkeypatch)
    batch_calls = []

    async def fake_post_json(url, payload, timeout, headers=None):
        if url.endswith("/batch"):
            batch_calls.append(payload)
            return {
                "context": f"CTX:{payload.get('query', '')}",
                "retrieve_status": "ok",
                "store_status": "stored" if payload.get("store_content") else "skipped",
            }
        if url.endswith("/speak"):
            return {"status": "ok", "mode": "tts", "wav_path": ""}
        raise AssertionError(f"unexpected url: {url}")

    class _Decision:
        should_trigger = False
        reason = ""

    monkeypatch.setattr(orchestrator, "post_json", fake_post_json)
    monkeypatch.setattr(orchestrator, "call_llm", lambda *_args, **_kwargs: "mock-answer")
    monkeypatch.setattr(orchestrator, "decide_agent_routing", lambda **_kwargs: _Decision())
    monkeypatch.setattr(
        orchestrator,
        "load_config",
        lambda: SimpleNamespace(system_prompt="", model_name="mock-model"),
    )

    client = TestClient(orchestrator.app)
    first = client.post(
        "/chat",
        json={
            "query": "hello-1",
            "user_id": "u1",
            "route_to_agent": False,
            "force_chat_only": False,
        },
    )
    second = client.post(
        "/chat",
        json={
            "query": "hello-2",
            "user_id": "u1",
            "route_to_agent": False,
            "force_chat_only": False,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    first_payload = first.json()
    second_payload = second.json()

    assert first_payload["memory_store_status"] == "deferred"
    assert first_payload["memory_store_flush_status"] == "skipped"
    assert second_payload["memory_store_status"] == "deferred"
    assert second_payload["memory_store_flush_status"] == "ok"

    assert len(batch_calls) == 2
    assert batch_calls[0]["query"] == "hello-1"
    assert batch_calls[0].get("store_content", "") == ""
    assert batch_calls[1]["query"] == "hello-2"
    assert batch_calls[1]["store_content"] == "用户: hello-1\nAI: mock-answer"


def test_orchestrator_voice_batch_returns_queued_when_tts_is_slow(monkeypatch):
    monkeypatch.setenv("ORCH_VOICE_ASYNC_BATCH_ENABLED", "1")
    monkeypatch.setenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_ENABLED", "0")
    monkeypatch.setenv("ORCH_VOICE_BATCH_RESULT_WAIT_SEC", "0.01")
    monkeypatch.setenv("ORCH_VOICE_BATCH_COLLECT_WINDOW_MS", "1")
    orchestrator = _reload_orchestrator_module(monkeypatch)

    async def fake_post_json(url, payload, timeout, headers=None):
        if url.endswith("/batch"):
            return {
                "context": "",
                "retrieve_status": "empty",
                "store_status": "skipped",
            }
        if url.endswith("/speak"):
            await asyncio.sleep(0.05)
            return {
                "status": "ok",
                "mode": "tts",
                "wav_path": "D:/tmp/slow.wav",
            }
        raise AssertionError(f"unexpected url: {url}")

    class _Decision:
        should_trigger = False
        reason = ""

    monkeypatch.setattr(orchestrator, "post_json", fake_post_json)
    monkeypatch.setattr(orchestrator, "call_llm", lambda *_args, **_kwargs: "mock-answer")
    monkeypatch.setattr(orchestrator, "decide_agent_routing", lambda **_kwargs: _Decision())
    monkeypatch.setattr(
        orchestrator,
        "load_config",
        lambda: SimpleNamespace(system_prompt="", model_name="mock-model"),
    )

    client = TestClient(orchestrator.app)
    response = client.post(
        "/chat",
        json={
            "query": "hello",
            "user_id": "u1",
            "route_to_agent": False,
            "force_chat_only": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "mock-answer"
    assert payload["tts"]["status"] == "queued"
    assert payload["tts"]["mode"] == "async-voice-batch"


def test_orchestrator_voice_hit_priority_direct_returns_wav(monkeypatch):
    monkeypatch.setenv("ORCH_VOICE_ASYNC_BATCH_ENABLED", "1")
    monkeypatch.setenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_ENABLED", "1")
    monkeypatch.setenv("ORCH_VOICE_HIT_PRIORITY_DIRECT_TIMEOUT_SEC", "0.2")
    orchestrator = _reload_orchestrator_module(monkeypatch)

    async def fake_post_json(url, payload, timeout, headers=None):
        if url.endswith("/batch"):
            return {
                "context": "",
                "retrieve_status": "empty",
                "store_status": "skipped",
            }
        if url.endswith("/speak"):
            await asyncio.sleep(0.02)
            return {
                "status": "ok",
                "mode": "tts",
                "wav_path": "D:/tmp/direct.wav",
            }
        raise AssertionError(f"unexpected url: {url}")

    class _Decision:
        should_trigger = False
        reason = ""

    monkeypatch.setattr(orchestrator, "post_json", fake_post_json)
    monkeypatch.setattr(orchestrator, "call_llm", lambda *_args, **_kwargs: "mock-answer")
    monkeypatch.setattr(orchestrator, "decide_agent_routing", lambda **_kwargs: _Decision())
    monkeypatch.setattr(
        orchestrator,
        "load_config",
        lambda: SimpleNamespace(system_prompt="", model_name="mock-model"),
    )

    client = TestClient(orchestrator.app)
    response = client.post(
        "/chat",
        json={
            "query": "hello",
            "user_id": "u1",
            "route_to_agent": False,
            "force_chat_only": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "mock-answer"
    assert payload["tts"]["status"] == "ok"
    assert payload["tts"]["wav_path"] == "D:/tmp/direct.wav"


def test_orchestrator_health_includes_voice_batch_metrics(monkeypatch):
    monkeypatch.setenv("ORCH_VOICE_ASYNC_BATCH_ENABLED", "1")
    orchestrator = _reload_orchestrator_module(monkeypatch)

    client = TestClient(orchestrator.app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert "voice_batch" in payload
    assert payload["voice_batch"]["enabled"] is True
    assert isinstance(payload["voice_batch"]["hit_priority_direct_enabled"], bool)
    assert isinstance(payload["voice_batch"]["hit_priority_direct_timeout_sec"], (int, float))
    assert isinstance(payload["voice_batch"]["queue_size"], int)
    assert isinstance(payload["voice_batch"]["worker_running"], bool)
    assert isinstance(payload["voice_batch"]["stats"], dict)
