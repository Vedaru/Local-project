import numpy as np
import pytest

from modules.memory.memoripy import rust_accel
from modules.memory.memoripy.memory_store import MemoryStore


@pytest.mark.unit
def test_compute_adjusted_scores_requires_rust_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rust_accel, "_RUST_BACKEND", None)
    monkeypatch.setattr(rust_accel, "_RUST_IMPORT_ATTEMPTED", True)

    with pytest.raises(RuntimeError, match="unavailable"):
        rust_accel.compute_adjusted_scores(
            query_embedding_norm=np.array([[1.0, 0.0]], dtype=np.float32),
            normalized_embeddings=[
                np.array([[1.0, 0.0]], dtype=np.float32),
                np.array([[0.0, 1.0]], dtype=np.float32),
            ],
            timestamps=[99.0, 99.0],
            access_counts=[2, 2],
            decay_factors=[1.0, 1.0],
            current_time=100.0,
            decay_rate=0.0001,
        )


@pytest.mark.unit
def test_compute_adjusted_scores_prefers_rust_backend(monkeypatch: pytest.MonkeyPatch):
    class _FakeRustBackend:
        @staticmethod
        def compute_adjusted_scores(*args, **kwargs):
            return [123.0, 0.5], [0.8, 0.7]

    monkeypatch.setattr(rust_accel, "_RUST_BACKEND", _FakeRustBackend())
    monkeypatch.setattr(rust_accel, "_RUST_IMPORT_ATTEMPTED", True)

    adjusted_scores, decayed_factors = rust_accel.compute_adjusted_scores(
        query_embedding_norm=np.array([[1.0, 0.0]], dtype=np.float32),
        normalized_embeddings=[
            np.array([[1.0, 0.0]], dtype=np.float32),
            np.array([[0.0, 1.0]], dtype=np.float32),
        ],
        timestamps=[99.0, 99.0],
        access_counts=[2, 2],
        decay_factors=[1.0, 1.0],
        current_time=100.0,
        decay_rate=0.0001,
    )

    assert adjusted_scores == [123.0, 0.5]
    assert decayed_factors == [0.8, 0.7]


@pytest.mark.unit
def test_memory_store_uses_accelerated_scores(monkeypatch: pytest.MonkeyPatch):
    call_state = {"called": False}

    def _fake_compute_adjusted_scores(*, query_embedding_norm, normalized_embeddings, **kwargs):
        call_state["called"] = True
        assert len(normalized_embeddings) == 2
        assert query_embedding_norm.shape == (1, 2)
        return [75.0, 5.0], [1.0, 1.0]

    monkeypatch.setattr(
        "modules.memory.memoripy.memory_store.compute_adjusted_scores",
        _fake_compute_adjusted_scores,
    )

    store = MemoryStore(dimension=2)
    now = 100.0

    store.add_interaction(
        {
            "id": "a",
            "prompt": "喜欢苹果",
            "output": "记住了",
            "embedding": [1.0, 0.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["苹果"],
            "decay_factor": 1.0,
        }
    )
    store.add_interaction(
        {
            "id": "b",
            "prompt": "喜欢香蕉",
            "output": "记住了",
            "embedding": [0.0, 1.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["香蕉"],
            "decay_factor": 1.0,
        }
    )

    results = store.retrieve(
        query_embedding=np.array([[1.0, 0.0]], dtype=np.float32),
        query_concepts=["苹果"],
        similarity_threshold=40,
    )

    assert call_state["called"] is True
    assert results
    assert any(interaction["id"] == "a" for interaction in results)


@pytest.mark.unit
def test_clear_layered_caches_prefers_rust_backend(monkeypatch: pytest.MonkeyPatch):
    state = {"called": False}

    class _FakeRustBackend:
        @staticmethod
        def clear_layered_caches():
            state["called"] = True

    monkeypatch.setattr(rust_accel, "_RUST_BACKEND", _FakeRustBackend())
    monkeypatch.setattr(rust_accel, "_RUST_IMPORT_ATTEMPTED", True)

    rust_accel.clear_layered_caches()

    assert state["called"] is True


@pytest.mark.unit
def test_get_layered_cache_stats_prefers_rust_backend(monkeypatch: pytest.MonkeyPatch):
    class _FakeRustBackend:
        @staticmethod
        def get_layered_cache_stats():
            return (11, 7, 5, 13, 9, 3)

    monkeypatch.setattr(rust_accel, "_RUST_BACKEND", _FakeRustBackend())
    monkeypatch.setattr(rust_accel, "_RUST_IMPORT_ATTEMPTED", True)

    stats = rust_accel.get_layered_cache_stats()

    assert stats == {
        "decay_hot_hits": 11,
        "decay_warm_hits": 7,
        "decay_misses": 5,
        "reinforcement_hot_hits": 13,
        "reinforcement_warm_hits": 9,
        "reinforcement_misses": 3,
    }


@pytest.mark.unit
def test_memory_store_retrieve_layered_cache_hits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_RETRIEVE_CACHE_TTL_SEC", "60")
    monkeypatch.setenv("MEMORY_RETRIEVE_L1_SIZE", "8")
    monkeypatch.setenv("MEMORY_RETRIEVE_L2_SIZE", "8")
    monkeypatch.setenv("MEMORY_RETRIEVE_L3_SIZE", "8")

    call_state = {"count": 0}

    def _fake_compute_adjusted_scores(*, normalized_embeddings, **kwargs):
        call_state["count"] += 1
        size = len(normalized_embeddings)
        return [80.0] + [5.0] * (size - 1), [1.0] * size

    monkeypatch.setattr(
        "modules.memory.memoripy.memory_store.compute_adjusted_scores",
        _fake_compute_adjusted_scores,
    )

    store = MemoryStore(dimension=2)
    now = 100.0
    store.add_interaction(
        {
            "id": "a",
            "prompt": "喜欢苹果",
            "output": "记住了",
            "embedding": [1.0, 0.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["苹果"],
            "decay_factor": 1.0,
        }
    )
    store.add_interaction(
        {
            "id": "b",
            "prompt": "喜欢香蕉",
            "output": "记住了",
            "embedding": [0.0, 1.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["香蕉"],
            "decay_factor": 1.0,
        }
    )

    first = store.retrieve(
        query_embedding=np.array([[1.0, 0.0]], dtype=np.float32),
        query_concepts=["苹果"],
        similarity_threshold=40,
    )
    second = store.retrieve(
        query_embedding=np.array([[1.0, 0.0]], dtype=np.float32),
        query_concepts=["苹果"],
        similarity_threshold=40,
    )

    stats = store.get_retrieval_cache_stats()

    assert call_state["count"] == 1
    assert first
    assert second
    assert first[0]["id"] == "a"
    assert second[0]["id"] == "a"
    assert stats["l1_hits"] >= 1


@pytest.mark.unit
def test_memory_store_retrieve_cache_invalidates_after_add(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_RETRIEVE_CACHE_TTL_SEC", "60")
    monkeypatch.setenv("MEMORY_RETRIEVE_L1_SIZE", "8")
    monkeypatch.setenv("MEMORY_RETRIEVE_L2_SIZE", "8")
    monkeypatch.setenv("MEMORY_RETRIEVE_L3_SIZE", "8")

    call_state = {"count": 0}

    def _fake_compute_adjusted_scores(*, normalized_embeddings, **kwargs):
        call_state["count"] += 1
        size = len(normalized_embeddings)
        return [80.0] + [5.0] * (size - 1), [1.0] * size

    monkeypatch.setattr(
        "modules.memory.memoripy.memory_store.compute_adjusted_scores",
        _fake_compute_adjusted_scores,
    )

    store = MemoryStore(dimension=2)
    now = 100.0
    store.add_interaction(
        {
            "id": "a",
            "prompt": "喜欢苹果",
            "output": "记住了",
            "embedding": [1.0, 0.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["苹果"],
            "decay_factor": 1.0,
        }
    )
    store.add_interaction(
        {
            "id": "b",
            "prompt": "喜欢香蕉",
            "output": "记住了",
            "embedding": [0.0, 1.0],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["香蕉"],
            "decay_factor": 1.0,
        }
    )

    store.retrieve(
        query_embedding=np.array([[1.0, 0.0]], dtype=np.float32),
        query_concepts=["苹果"],
        similarity_threshold=40,
    )

    store.add_interaction(
        {
            "id": "c",
            "prompt": "喜欢樱桃",
            "output": "记住了",
            "embedding": [0.8, 0.2],
            "timestamp": now,
            "access_count": 1,
            "concepts": ["樱桃"],
            "decay_factor": 1.0,
        }
    )

    store.retrieve(
        query_embedding=np.array([[1.0, 0.0]], dtype=np.float32),
        query_concepts=["苹果"],
        similarity_threshold=40,
    )

    stats = store.get_retrieval_cache_stats()

    assert call_state["count"] == 2
    assert stats["misses"] >= 2
