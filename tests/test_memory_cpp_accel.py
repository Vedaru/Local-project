import pytest

from modules.memory.core import HumanMemoryEngine
from modules.memory.episodic import EpisodicMemory


class _FakeMemoryCppBackend:
    def __init__(self, dimension: int = 8) -> None:
        self.library_path = "fake-memory-cpp-engine"
        self.dimension = dimension
        self.hash_calls = 0
        self.score_calls = 0

    def hash_embed_text(self, text: str, *, dimension: int):
        self.hash_calls += 1
        vec = [0.0] * max(1, int(dimension))
        lowered = (text or "").lower()
        if "alpha" in lowered:
            vec[0] = 1.0
        elif "beta" in lowered:
            vec[1] = 1.0
        else:
            vec[2] = 1.0
        return vec

    def compute_adjusted_scores(
        self,
        *,
        query_embedding,
        candidate_embeddings,
        timestamps,
        access_counts,
        decay_factors,
        current_time,
        decay_rate,
        worker_count=0,
    ):
        _ = (
            query_embedding,
            timestamps,
            access_counts,
            decay_factors,
            current_time,
            decay_rate,
            worker_count,
        )
        self.score_calls += 1
        scores = [float(embedding[0]) * 100.0 for embedding in candidate_embeddings]
        return scores, [1.0] * len(scores)


class _BrokenMemoryCppBackend:
    library_path = "broken-memory-cpp-engine"

    def hash_embed_text(self, text: str, *, dimension: int):
        _ = (text, dimension)
        return None

    def compute_adjusted_scores(self, **kwargs):
        _ = kwargs
        return None


@pytest.mark.unit
def test_episodic_search_uses_cpp_backend_scores(tmp_path):
    backend = _FakeMemoryCppBackend()
    memory = EpisodicMemory(
        path=str(tmp_path / "episodes.jsonl"),
        max_episodes=32,
        similarity_threshold=0.2,
        cpp_backend=backend,
        cpp_embedding_dim=8,
        cpp_decay_rate=0.0001,
    )

    memory.add_episode("alpha user", "alpha assistant")
    memory.add_episode("beta user", "beta assistant")

    results = memory.search("alpha", top_k=2)

    assert results
    assert results[0].user_input == "alpha user"
    assert backend.hash_calls >= 2
    assert backend.score_calls >= 1


@pytest.mark.unit
def test_episodic_search_falls_back_when_cpp_unavailable(tmp_path):
    backend = _BrokenMemoryCppBackend()
    memory = EpisodicMemory(
        path=str(tmp_path / "episodes.jsonl"),
        max_episodes=32,
        similarity_threshold=0.2,
        cpp_backend=backend,
        cpp_embedding_dim=8,
    )

    memory.add_episode("foo keyword here", "assistant text")
    memory.add_episode("bar unrelated", "assistant text")

    results = memory.search("foo", top_k=2)

    assert results
    assert results[0].user_input == "foo keyword here"


@pytest.mark.unit
def test_human_memory_engine_stats_include_cpp_flags(tmp_path, monkeypatch: pytest.MonkeyPatch):
    backend = _FakeMemoryCppBackend()

    monkeypatch.setattr("modules.memory.core.load_memory_cpp_backend", lambda **kwargs: backend)

    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))
    stats = engine.stats()

    assert stats["memory_cpp_accel_enabled"] is True
    assert stats["memory_cpp_accel_library"] == backend.library_path
    engine.close()
