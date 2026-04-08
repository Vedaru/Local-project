from __future__ import annotations

import importlib


class _DummyEngine:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _BadEngine:
    def close(self):
        raise RuntimeError("close failed")


class _CaptureEngine:
    def __init__(self):
        self.store_calls = []
        self.retrieve_calls = []

    def store(self, content, metadata=None):
        self.store_calls.append({"content": content, "metadata": metadata or {}})
        return "stored"

    def retrieve(self, query, n_results=5, user_id=None):
        self.retrieve_calls.append({"query": query, "n_results": n_results, "user_id": user_id})
        return f"ctx-{user_id}"


def _reload_memory_service_module():
    import microservices.memory_service.main as memory_service

    return importlib.reload(memory_service)


def test_reset_engine_for_tests_closes_cached_engine() -> None:
    memory_service = _reload_memory_service_module()
    dummy = _DummyEngine()

    memory_service._set_cached_engine(dummy)
    memory_service.reset_engine_for_tests()

    assert dummy.closed is True
    assert memory_service._engine is None
    assert getattr(memory_service.app.state, "memory_engine", None) is None


def test_close_sync_handles_close_errors_and_clears_cache() -> None:
    memory_service = _reload_memory_service_module()
    memory_service._set_cached_engine(_BadEngine())

    result = memory_service._close_sync()

    assert result["status"] == "closed"
    assert memory_service._engine is None
    assert getattr(memory_service.app.state, "memory_engine", None) is None


def test_get_engine_uses_lazy_singleton(monkeypatch) -> None:
    memory_service = _reload_memory_service_module()
    memory_service.reset_engine_for_tests()

    dummy = _DummyEngine()

    def _fake_human_memory_engine(*args, **kwargs):
        return dummy

    monkeypatch.setattr(memory_service, "HumanMemoryEngine", _fake_human_memory_engine)
    monkeypatch.setattr(memory_service, "_create_llm_extract_fn", lambda: None)

    first = memory_service._get_engine()
    second = memory_service._get_engine()

    assert first is dummy
    assert second is dummy


def test_batch_sync_passes_user_id_to_store_and_retrieve(monkeypatch) -> None:
    memory_service = _reload_memory_service_module()
    capture = _CaptureEngine()

    monkeypatch.setattr(memory_service, "_get_engine", lambda: capture)

    req = memory_service.BatchRequest(
        query="你还记得我的偏好吗",
        user_id="alice",
        n_results=4,
        retrieve=True,
        store_content="用户: 我喜欢苹果\nAI: 好的，记住了",
    )

    result = memory_service._batch_sync(req)

    assert result["store_status"] == "stored"
    assert result["context"] == "ctx-alice"
    assert capture.store_calls
    assert capture.store_calls[0]["metadata"]["user_id"] == "alice"
    assert capture.retrieve_calls
    assert capture.retrieve_calls[0]["user_id"] == "alice"


def test_store_sync_passes_user_id(monkeypatch) -> None:
    memory_service = _reload_memory_service_module()
    capture = _CaptureEngine()

    monkeypatch.setattr(memory_service, "_get_engine", lambda: capture)

    result = memory_service._store_sync("用户: 我喜欢香蕉\nAI: 好的", "bob")

    assert result["status"] == "stored"
    assert capture.store_calls
    assert capture.store_calls[0]["metadata"]["user_id"] == "bob"
