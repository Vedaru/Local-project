from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from .logging_config import get_logger

logger = get_logger("voice_cpp_accel")

_PY_BYTES_AS_STRING = ctypes.pythonapi.PyBytes_AsString
_PY_BYTES_AS_STRING.argtypes = [ctypes.py_object]
_PY_BYTES_AS_STRING.restype = ctypes.c_void_p


def _as_uint8_pointer(data: bytes | bytearray) -> tuple[object, object]:
    if isinstance(data, bytes):
        address = int(_PY_BYTES_AS_STRING(data))
        pointer = ctypes.cast(address, ctypes.POINTER(ctypes.c_uint8))
        return pointer, data

    if isinstance(data, bytearray):
        if not data:
            return ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_uint8)), data
        view = (ctypes.c_uint8 * len(data)).from_buffer(data)
        pointer = ctypes.cast(view, ctypes.POINTER(ctypes.c_uint8))
        return pointer, view

    raise TypeError("pcm buffer must be bytes or bytearray")


def _as_int16_pointer(data: bytes | bytearray) -> tuple[object, int, object]:
    sample_count = len(data) // 2
    if sample_count <= 0:
        return ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_int16)), 0, data

    if isinstance(data, bytes):
        address = int(_PY_BYTES_AS_STRING(data))
        pointer = ctypes.cast(address, ctypes.POINTER(ctypes.c_int16))
        return pointer, sample_count, data

    if isinstance(data, bytearray):
        view = (ctypes.c_int16 * sample_count).from_buffer(data)
        pointer = ctypes.cast(view, ctypes.POINTER(ctypes.c_int16))
        return pointer, sample_count, view

    raise TypeError("pcm buffer must be bytes or bytearray")


class VoiceCppBackend:
    def __init__(self, library: ctypes.CDLL, library_path: Path) -> None:
        self._library = library
        self.library_path = str(library_path)

        self._write_wav = self._library.write_wav_mono16le_cpp
        self._write_wav.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.c_uint32,
        ]
        self._write_wav.restype = ctypes.c_int

        self._compute_volume = self._library.compute_pcm_volume_cpp
        self._compute_volume.argtypes = [
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_size_t,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
        ]
        self._compute_volume.restype = ctypes.c_int

        self._compute_volume_batch = self._library.compute_pcm_volume_batch_cpp
        self._compute_volume_batch.argtypes = [
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._compute_volume_batch.restype = ctypes.c_int

        self._build_chunk_index = getattr(self._library, "build_chunk_index_cpp", None)
        if self._build_chunk_index is not None:
            self._build_chunk_index.argtypes = [
                ctypes.c_size_t,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            self._build_chunk_index.restype = ctypes.c_int

    def save_pcm_mono16(self, wav_path: str, pcm_data: bytes | bytearray, sample_rate: int) -> bool:
        pcm_data = pcm_data or b""
        if not wav_path or int(sample_rate or 0) <= 0:
            return False
        if len(pcm_data) % 2 != 0:
            return False

        path_bytes = os.fspath(wav_path).encode("utf-8")
        pcm_ptr, keepalive = _as_uint8_pointer(pcm_data)
        _ = keepalive
        result = int(self._write_wav(path_bytes, pcm_ptr, len(pcm_data), int(sample_rate)))
        return result == 0

    def compute_volume_from_pcm16(
        self,
        pcm_chunk: bytes | bytearray,
        *,
        gate: float,
        normalizer: float,
        power: float,
    ) -> Optional[float]:
        if not pcm_chunk:
            return 0.0

        sample_count = len(pcm_chunk) // 2
        if sample_count <= 0:
            return 0.0
        if len(pcm_chunk) % 2 != 0:
            return None

        sample_ptr, sample_count, keepalive = _as_int16_pointer(pcm_chunk)
        _ = keepalive

        out_volume = ctypes.c_double(0.0)
        result = int(
            self._compute_volume(
                sample_ptr,
                sample_count,
                float(gate),
                float(normalizer),
                float(power),
                ctypes.byref(out_volume),
            )
        )
        if result != 0:
            return None

        value = float(out_volume.value)
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    def compute_volume_batch_from_pcm16(
        self,
        pcm_chunk: bytes | bytearray,
        *,
        frame_samples: int,
        gate: float,
        normalizer: float,
        power: float,
    ) -> Optional[list[float]]:
        if not pcm_chunk:
            return []
        if len(pcm_chunk) % 2 != 0:
            return None
        if int(frame_samples or 0) <= 0:
            return []

        sample_ptr, sample_count, keepalive = _as_int16_pointer(pcm_chunk)
        _ = keepalive
        frame_samples = int(frame_samples)
        frame_count = sample_count // frame_samples
        if frame_count <= 0:
            return []

        out_values = (ctypes.c_double * frame_count)()
        out_count = ctypes.c_size_t(0)
        result = int(
            self._compute_volume_batch(
                sample_ptr,
                sample_count,
                frame_samples,
                float(gate),
                float(normalizer),
                float(power),
                out_values,
                frame_count,
                ctypes.byref(out_count),
            )
        )
        if result != 0:
            return None

        actual_count = min(int(out_count.value), frame_count)
        volumes: list[float] = []
        for index in range(actual_count):
            value = float(out_values[index])
            if value < 0.0:
                value = 0.0
            elif value > 1.0:
                value = 1.0
            volumes.append(value)
        return volumes

    def build_chunk_index(self, total_size: int, chunk_size: int) -> Optional[list[tuple[int, int]]]:
        if self._build_chunk_index is None:
            return None

        total_size = int(total_size or 0)
        chunk_size = int(chunk_size or 0)
        if total_size <= 0:
            return []
        if chunk_size <= 0:
            return []

        chunk_count = (total_size + chunk_size - 1) // chunk_size
        offsets = (ctypes.c_size_t * chunk_count)()
        sizes = (ctypes.c_size_t * chunk_count)()
        out_count = ctypes.c_size_t(0)

        result = int(
            self._build_chunk_index(
                total_size,
                chunk_size,
                offsets,
                sizes,
                chunk_count,
                ctypes.byref(out_count),
            )
        )
        if result != 0:
            return None

        actual_count = min(int(out_count.value), chunk_count)
        chunk_index: list[tuple[int, int]] = []
        for index in range(actual_count):
            offset = int(offsets[index])
            size = int(sizes[index])
            if size <= 0:
                continue
            chunk_index.append((offset, size))
        return chunk_index


_backend_lock = threading.Lock()
_backend_cache: Optional[VoiceCppBackend] = None
_backend_attempted = False
_backend_error: Optional[str] = None
_windows_dll_handles: list[object] = []
_windows_dll_dirs_seen: set[str] = set()


def _candidate_library_paths(explicit_library: str = "") -> list[Path]:
    root_dir = Path(__file__).resolve().parents[1]
    explicit_library = (explicit_library or "").strip()
    env_library = (os.getenv("VOICE_CPP_ACCEL_LIB", "") or "").strip()

    candidates: list[Path] = []
    if explicit_library:
        candidates.append(Path(explicit_library))
    if env_library:
        candidates.append(Path(env_library))

    if os.name == "nt":
        library_names = ["voice_cpp_engine.dll"]
    elif os.name == "posix" and "darwin" in sys.platform:
        library_names = ["voice_cpp_engine.dylib", "libvoice_cpp_engine.dylib"]
    else:
        library_names = ["voice_cpp_engine.so", "libvoice_cpp_engine.so"]

    search_dirs = [
        root_dir / "build" / "voice_cpp_engine",
        root_dir / "build" / "voice_cpp_engine" / "Release",
        root_dir / "build" / "voice_cpp_engine" / "Debug",
        root_dir / "cpp_modules" / "voice_cpp_engine" / "build",
        root_dir / "cpp_modules" / "voice_cpp_engine" / "build" / "Release",
        root_dir / "cpp_modules" / "voice_cpp_engine" / "build" / "Debug",
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


def load_voice_cpp_backend(*, explicit_library: str = "") -> VoiceCppBackend:
    global _backend_cache
    global _backend_attempted
    global _backend_error

    with _backend_lock:
        if _backend_cache is not None:
            return _backend_cache

        if _backend_attempted and _backend_error:
            raise RuntimeError(_backend_error)

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
                _backend_cache = VoiceCppBackend(library=library, library_path=candidate)
                logger.info("Voice C++ acceleration loaded: %s", candidate)
                return _backend_cache
            except OSError as exc:
                logger.warning("Failed to load voice C++ acceleration (%s): %s", candidate, exc)
                errors.append(f"{candidate}: {exc}")
            except Exception as exc:
                logger.warning("Failed to initialize voice C++ backend (%s): %s", candidate, exc)
                errors.append(f"{candidate}: {exc}")

        if attempted_paths:
            detail = "; ".join(errors) if errors else "no successful candidate"
            _backend_error = (
                "Voice C++ acceleration backend is required but failed to load. "
                f"Tried {len(attempted_paths)} path(s): {', '.join(attempted_paths)}. "
                f"Details: {detail}"
            )
        else:
            _backend_error = (
                "Voice C++ acceleration backend is required but no library file was found in candidate paths."
            )

        raise RuntimeError(_backend_error)
