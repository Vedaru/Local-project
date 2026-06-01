"""
Memory C++ 加速后端 — FFI 绑定 memory_cpp_engine 库

提供 FNV 哈希嵌入和多线程记忆评分计算能力。
DLL 搜索路径和候选库发现逻辑委托给 cpp_accel_common。
"""

from __future__ import annotations

import ctypes
import threading
from array import array
from pathlib import Path
from typing import Optional, Sequence

from .cpp_accel_common import as_bytes_pointer, load_cpp_backend_common
from .logging_config import get_logger

logger = get_logger("memory_cpp_accel")


class MemoryCppBackend:
    def __init__(self, library: ctypes.CDLL, library_path: Path) -> None:
        self._library = library
        self.library_path = str(library_path)

        self._hash_embed_text = self._library.hash_embed_text_cpp
        self._hash_embed_text.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float),
        ]
        self._hash_embed_text.restype = ctypes.c_int

        self._compute_adjusted_scores = self._library.compute_adjusted_scores_with_threads_cpp
        self._compute_adjusted_scores.argtypes = [
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self._compute_adjusted_scores.restype = ctypes.c_int

    def hash_embed_text(self, text: str, *, dimension: int) -> Optional[list[float]]:
        dimension = int(dimension or 0)
        if dimension <= 0:
            return []

        text_bytes = (text or "").encode("utf-8", errors="ignore")
        text_ptr, keepalive = as_bytes_pointer(text_bytes)
        _ = keepalive

        out_embedding = (ctypes.c_float * dimension)()
        result = int(
            self._hash_embed_text(
                text_ptr,
                len(text_bytes),
                dimension,
                out_embedding,
            )
        )
        if result != 0:
            return None

        return [float(out_embedding[idx]) for idx in range(dimension)]

    def compute_adjusted_scores(
        self,
        *,
        query_embedding: Sequence[float],
        candidate_embeddings: Sequence[Sequence[float]],
        timestamps: Sequence[float],
        access_counts: Sequence[int],
        decay_factors: Sequence[float],
        current_time: float,
        decay_rate: float,
        worker_count: int = 0,
    ) -> Optional[tuple[list[float], list[float]]]:
        candidate_count = len(candidate_embeddings)
        if candidate_count <= 0:
            return ([], [])

        dimension = len(query_embedding)
        if dimension <= 0:
            return ([], [])

        if len(timestamps) != candidate_count:
            return None
        if len(access_counts) != candidate_count:
            return None
        if len(decay_factors) != candidate_count:
            return None

        for embedding in candidate_embeddings:
            if len(embedding) != dimension:
                return None

        query_array = array("f", (float(v) for v in query_embedding))
        candidate_array = array("f")
        for embedding in candidate_embeddings:
            candidate_array.extend(float(v) for v in embedding)

        timestamp_array = array("d", (float(v) for v in timestamps))
        access_array = array("Q", (int(max(0, int(v))) for v in access_counts))
        decay_array = array("d", (float(v) for v in decay_factors))

        query_buf = (ctypes.c_float * dimension).from_buffer(query_array)
        candidate_buf = (ctypes.c_float * (candidate_count * dimension)).from_buffer(candidate_array)
        timestamp_buf = (ctypes.c_double * candidate_count).from_buffer(timestamp_array)
        access_buf = (ctypes.c_uint64 * candidate_count).from_buffer(access_array)
        decay_buf = (ctypes.c_double * candidate_count).from_buffer(decay_array)

        out_scores = (ctypes.c_double * candidate_count)()
        out_decays = (ctypes.c_double * candidate_count)()

        result = int(
            self._compute_adjusted_scores(
                query_buf,
                dimension,
                candidate_buf,
                candidate_count,
                timestamp_buf,
                access_buf,
                decay_buf,
                float(current_time),
                float(decay_rate),
                int(max(0, worker_count)),
                out_scores,
                out_decays,
            )
        )
        if result != 0:
            return None

        scores = [float(out_scores[idx]) for idx in range(candidate_count)]
        decays = [float(out_decays[idx]) for idx in range(candidate_count)]
        return (scores, decays)


_backend_lock = threading.Lock()
_backend_cache: Optional[MemoryCppBackend] = None
_backend_attempted = False
_backend_error: Optional[str] = None


def load_memory_cpp_backend(*, explicit_library: str = "", required: bool = False) -> Optional[MemoryCppBackend]:
    global _backend_cache
    global _backend_attempted
    global _backend_error

    with _backend_lock:
        if _backend_cache is not None:
            return _backend_cache

        if _backend_attempted and _backend_error:
            if required:
                raise RuntimeError(_backend_error)
            return None

        _backend_attempted = True

    # 使用公共加载器（在锁外执行 I/O 和 CDLL 加载）
    def _factory(library: ctypes.CDLL, library_path: Path) -> MemoryCppBackend:
        return MemoryCppBackend(library=library, library_path=library_path)

    result = load_cpp_backend_common(
        library_name="memory_cpp_engine.dll",
        env_var_name="MEMORY_CPP_ACCEL_LIB",
        module_name="memory_cpp_engine",
        backend_factory=_factory,
        explicit_library=explicit_library,
        logger_name="memory_cpp_accel",
        required=required,
    )

    with _backend_lock:
        if result is not None:
            _backend_cache = result  # type: ignore[assignment]
        else:
            _backend_error = "Memory C++ acceleration backend failed to load."

    return result  # type: ignore[return-value]
