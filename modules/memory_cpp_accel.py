from __future__ import annotations

import ctypes
import os
import sys
import threading
from array import array
from pathlib import Path
from typing import Optional, Sequence

from .logging_config import get_logger

logger = get_logger("memory_cpp_accel")

_PY_BYTES_AS_STRING = ctypes.pythonapi.PyBytes_AsString
_PY_BYTES_AS_STRING.argtypes = [ctypes.py_object]
_PY_BYTES_AS_STRING.restype = ctypes.c_void_p


def _as_bytes_pointer(data: bytes) -> tuple[object, object]:
    if not data:
        return ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_uint8)), data

    address = int(_PY_BYTES_AS_STRING(data))
    pointer = ctypes.cast(address, ctypes.POINTER(ctypes.c_uint8))
    return pointer, data


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
        text_ptr, keepalive = _as_bytes_pointer(text_bytes)
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
_windows_dll_handles: list[object] = []
_windows_dll_dirs_seen: set[str] = set()


def _candidate_library_paths(explicit_library: str = "") -> list[Path]:
    root_dir = Path(__file__).resolve().parents[1]
    explicit_library = (explicit_library or "").strip()
    env_library = (os.getenv("MEMORY_CPP_ACCEL_LIB", "") or "").strip()

    candidates: list[Path] = []
    if explicit_library:
        candidates.append(Path(explicit_library))
    if env_library:
        candidates.append(Path(env_library))

    if os.name == "nt":
        library_names = ["memory_cpp_engine.dll"]
    elif os.name == "posix" and "darwin" in sys.platform:
        library_names = ["memory_cpp_engine.dylib", "libmemory_cpp_engine.dylib"]
    else:
        library_names = ["memory_cpp_engine.so", "libmemory_cpp_engine.so"]

    search_dirs = [
        root_dir / "build" / "memory_cpp_engine",
        root_dir / "build" / "memory_cpp_engine" / "Release",
        root_dir / "build" / "memory_cpp_engine" / "Debug",
        root_dir / "cpp_modules" / "memory_cpp_engine" / "build",
        root_dir / "cpp_modules" / "memory_cpp_engine" / "build" / "Release",
        root_dir / "cpp_modules" / "memory_cpp_engine" / "build" / "Debug",
    ]

    for search_dir in search_dirs:
        for library_name in library_names:
            candidates.append(search_dir / library_name)

    deduplicated: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)

    return deduplicated


def _register_windows_dll_dirs(extra_dirs: list[Path]) -> None:
    if os.name != "nt":
        return

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return

    candidate_dirs: list[Path] = []
    candidate_dirs.extend(extra_dirs)

    path_raw = os.environ.get("PATH", "")
    if path_raw:
        for item in path_raw.split(os.pathsep):
            item = item.strip().strip('"')
            if item:
                candidate_dirs.append(Path(item))

    candidate_dirs.extend(
        [
            Path("D:/mingw64/bin"),
            Path("C:/mingw64/bin"),
            Path.home()
            / "AppData"
            / "Local"
            / "Microsoft"
            / "WinGet"
            / "Packages"
            / "BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "mingw64"
            / "bin",
            Path.home()
            / "AppData"
            / "Local"
            / "Microsoft"
            / "WinGet"
            / "Packages"
            / "MartinStorsjo.LLVM-MinGW.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "llvm-mingw-20260324-ucrt-x86_64"
            / "bin",
        ]
    )

    for candidate_dir in candidate_dirs:
        try:
            resolved = str(candidate_dir.resolve())
        except Exception:
            resolved = str(candidate_dir)

        normalized = resolved.lower().rstrip("\\/")
        if not normalized or normalized in _windows_dll_dirs_seen:
            continue
        if not Path(resolved).exists():
            continue

        try:
            handle = add_dll_directory(resolved)
            _windows_dll_handles.append(handle)
            _windows_dll_dirs_seen.add(normalized)
        except Exception:
            continue


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
        errors: list[str] = []
        attempted_paths: list[str] = []

        for candidate in _candidate_library_paths(explicit_library=explicit_library):
            if not candidate.exists() or not candidate.is_file():
                continue
            attempted_paths.append(str(candidate))
            try:
                _register_windows_dll_dirs([candidate.parent])
                library = ctypes.CDLL(str(candidate))
                _backend_cache = MemoryCppBackend(library=library, library_path=candidate)
                logger.info("Memory C++ acceleration loaded: %s", candidate)
                return _backend_cache
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        if attempted_paths:
            detail = "; ".join(errors) if errors else "no successful candidate"
            _backend_error = (
                "Memory C++ acceleration backend failed to load. "
                f"Tried {len(attempted_paths)} path(s): {', '.join(attempted_paths)}. "
                f"Details: {detail}"
            )
        else:
            _backend_error = "Memory C++ acceleration backend library file was not found in candidate paths."

        if required:
            raise RuntimeError(_backend_error)

        logger.warning(_backend_error)
        return None
