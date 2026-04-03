import numpy as np
import pytest

from modules.memory.models import RustHashEmbeddingModel
from modules.memory import wrapper as memory_wrapper
from modules.memory.memoripy.in_memory_storage import InMemoryStorage
from modules.memory.memoripy.memory_manager import MemoryManager as MemoripyManager
from modules.memory.memoripy.model import ChatModel, EmbeddingModel


@pytest.mark.unit
def test_create_embedding_model_falls_back_once_to_hash(monkeypatch: pytest.MonkeyPatch):
    class _ArkFail:
        def __init__(self):
            raise RuntimeError("ark unavailable")

    class _HashOk:
        def __init__(self):
            self.backend = "hash"

    monkeypatch.setenv("MEMORY_EMBEDDING_BACKEND", "ark")
    monkeypatch.setattr(memory_wrapper, "ArkEmbeddingModel", _ArkFail)
    monkeypatch.setattr(memory_wrapper, "HashEmbeddingModel", _HashOk)

    model = memory_wrapper.MemoryManager._create_embedding_model()
    assert isinstance(model, _HashOk)


@pytest.mark.unit
def test_create_embedding_model_raises_when_hash_also_unavailable(monkeypatch: pytest.MonkeyPatch):
    class _ArkFail:
        def __init__(self):
            raise RuntimeError("ark unavailable")

    class _HashFail:
        def __init__(self):
            raise RuntimeError("hash unavailable")

    monkeypatch.setenv("MEMORY_EMBEDDING_BACKEND", "ark")
    monkeypatch.setattr(memory_wrapper, "ArkEmbeddingModel", _ArkFail)
    monkeypatch.setattr(memory_wrapper, "HashEmbeddingModel", _HashFail)

    with pytest.raises(RuntimeError, match="无法初始化嵌入模型"):
        memory_wrapper.MemoryManager._create_embedding_model()


class _DummyChatModel(ChatModel):
    def invoke(self, messages: list) -> str:
        return "ok"

    def extract_concepts(self, text: str) -> list[str]:
        return []


class _DummyEmbeddingModel(EmbeddingModel):
    def __init__(self):
        self.calls = 0

    def get_embedding(self, text: str) -> np.ndarray:
        self.calls += 1
        return np.array([1.0, 2.0], dtype=np.float32)

    def initialize_embedding_dimension(self) -> int:
        return 2


@pytest.mark.unit
def test_memoripy_embedding_cache_reuses_previous_result(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_EMBED_CACHE_SIZE", "8")

    embed_model = _DummyEmbeddingModel()
    manager = MemoripyManager(
        chat_model=_DummyChatModel(),
        embedding_model=embed_model,
        storage=InMemoryStorage(),
    )

    first = manager.get_embedding("重复查询")
    second = manager.get_embedding("重复查询")

    assert first.shape == (1, 2)
    assert second.shape == (1, 2)
    assert embed_model.calls == 1


@pytest.mark.unit
def test_rust_hash_embedding_model_uses_backend(monkeypatch: pytest.MonkeyPatch):
    class _FakeBackend:
        @staticmethod
        def hash_embed_text(_text: str, dim: int):
            return [0.5] * dim

    monkeypatch.setattr(
        "modules.memory.memoripy.rust_accel._load_rust_backend",
        lambda: _FakeBackend(),
    )

    model = RustHashEmbeddingModel(dimension=6)
    vector = model.get_embedding("hello")

    assert vector.shape == (6,)
    assert np.allclose(vector, np.array([0.5] * 6, dtype=np.float32))


@pytest.mark.unit
def test_rust_hash_embedding_model_requires_hash_function(monkeypatch: pytest.MonkeyPatch):
    class _BackendWithoutHash:
        pass

    monkeypatch.setattr(
        "modules.memory.memoripy.rust_accel._load_rust_backend",
        lambda: _BackendWithoutHash(),
    )

    with pytest.raises(RuntimeError, match="hash_embed_text"):
        RustHashEmbeddingModel(dimension=6)