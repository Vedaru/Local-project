"""Rust acceleration bridge for memoripy retrieval scoring."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np

_RUST_BACKEND: Optional[object] = None
_RUST_IMPORT_ATTEMPTED = False
_DLL_DIR_HANDLES: list[object] = []


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_windows_dll_dirs() -> None:
    if os.name != "nt":
        return

    candidate_dirs: list[Path] = []

    # Rust GNU LLVM package default install location
    candidate_dirs.append(Path("C:/Program Files/Rust stable LLVM 1.94/bin"))

    # LLVM-MinGW installation from winget (provides libgcc/libstdc++ runtime DLLs)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.exists():
            for package_dir in winget_root.glob("MartinStorsjo.LLVM-MinGW*"):
                for dist_dir in package_dir.glob("llvm-mingw-*"):
                    candidate_dirs.append(dist_dir / "bin")

    for candidate in candidate_dirs:
        if not candidate.exists():
            continue

        candidate_str = str(candidate)

        # Keep handle references alive for process lifetime.
        try:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(candidate_str))
        except Exception:
            pass

        path_segments = [segment for segment in os.environ.get("PATH", "").split(";") if segment]
        if candidate_str not in path_segments:
            os.environ["PATH"] = candidate_str + ";" + os.environ.get("PATH", "")


def _ensure_rust_target_on_syspath() -> None:
    release_dir = _project_root() / "rust_modules" / "memory_accel" / "target" / "release"
    if release_dir.exists():
        release_dir_str = str(release_dir)
        if release_dir_str not in sys.path:
            sys.path.insert(0, release_dir_str)


def _load_rust_backend() -> Optional[object]:
    global _RUST_BACKEND
    global _RUST_IMPORT_ATTEMPTED

    if _RUST_IMPORT_ATTEMPTED:
        return _RUST_BACKEND

    _RUST_IMPORT_ATTEMPTED = True
    _ensure_rust_target_on_syspath()
    _ensure_windows_dll_dirs()

    for module_name in ("modules.memory._memory_rust", "_memory_rust"):
        try:
            _RUST_BACKEND = importlib.import_module(module_name)
            break
        except Exception:
            continue

    return _RUST_BACKEND


def is_rust_acceleration_available() -> bool:
    return _load_rust_backend() is not None


def clear_layered_caches() -> None:
    backend = _load_rust_backend()
    if backend is None:
        return

    clear_fn = getattr(backend, "clear_layered_caches", None)
    if callable(clear_fn):
        clear_fn()


def get_layered_cache_stats() -> dict[str, int]:
    backend = _load_rust_backend()
    if backend is None:
        raise RuntimeError("Rust memory acceleration backend is unavailable.")

    stats_fn = getattr(backend, "get_layered_cache_stats", None)
    if not callable(stats_fn):
        raise RuntimeError("Rust layered cache stats API is unavailable.")

    payload = stats_fn()
    if not isinstance(payload, (tuple, list)) or len(payload) != 6:
        raise RuntimeError("Rust layered cache stats payload is invalid.")

    return {
        "decay_hot_hits": int(payload[0]),
        "decay_warm_hits": int(payload[1]),
        "decay_misses": int(payload[2]),
        "reinforcement_hot_hits": int(payload[3]),
        "reinforcement_warm_hits": int(payload[4]),
        "reinforcement_misses": int(payload[5]),
    }


def compute_adjusted_scores(
    query_embedding_norm: np.ndarray,
    normalized_embeddings: list[np.ndarray],
    timestamps: list[float],
    access_counts: list[int],
    decay_factors: list[float],
    current_time: float,
    decay_rate: float,
) -> tuple[list[float], list[float]]:
    """Compute adjusted similarity scores with Rust backend only."""
    if not normalized_embeddings:
        return [], []

    backend = _load_rust_backend()
    if backend is None:
        raise RuntimeError("Rust memory acceleration backend is unavailable.")

    try:
        query_payload = np.asarray(query_embedding_norm, dtype=np.float32).reshape(-1).tolist()
        embedding_payload = [
            np.asarray(embedding, dtype=np.float32).reshape(-1).tolist() for embedding in normalized_embeddings
        ]
        return backend.compute_adjusted_scores(
            query_payload,
            embedding_payload,
            [float(ts) for ts in timestamps],
            [int(count) for count in access_counts],
            [float(decay) for decay in decay_factors],
            float(current_time),
            float(decay_rate),
        )
    except Exception as exc:
        raise RuntimeError(f"Rust memory acceleration failed: {exc}") from exc
