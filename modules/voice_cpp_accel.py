from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Optional

from .logging_config import get_logger

logger = get_logger("voice_cpp_accel")

_ENABLED_VALUES = {"1", "true", "yes", "on"}


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

    def save_pcm_mono16(self, wav_path: str, pcm_data: bytes, sample_rate: int) -> bool:
        pcm_data = pcm_data or b""
        if not wav_path or int(sample_rate or 0) <= 0:
            return False
        if len(pcm_data) % 2 != 0:
            return False

        path_bytes = os.fspath(wav_path).encode("utf-8")
        pcm_buffer = ctypes.create_string_buffer(pcm_data)
        pcm_ptr = ctypes.cast(pcm_buffer, ctypes.POINTER(ctypes.c_uint8))
        result = int(self._write_wav(path_bytes, pcm_ptr, len(pcm_data), int(sample_rate)))
        return result == 0

    def compute_volume_from_pcm16(
        self,
        pcm_chunk: bytes,
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

        packed = pcm_chunk[: sample_count * 2]
        sample_buffer = ctypes.create_string_buffer(packed)
        sample_ptr = ctypes.cast(sample_buffer, ctypes.POINTER(ctypes.c_int16))

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


_backend_lock = threading.Lock()
_backend_cache: Optional[VoiceCppBackend] = None
_backend_attempted = False
_windows_dll_handles: list[object] = []
_windows_dll_dirs_seen: set[str] = set()


def _is_cpp_accel_enabled() -> bool:
    raw_value = (os.getenv("VOICE_CPP_ACCEL_ENABLED", "1") or "1").strip().lower()
    return raw_value in _ENABLED_VALUES


def _candidate_library_paths() -> list[Path]:
    root_dir = Path(__file__).resolve().parents[1]
    env_library = (os.getenv("VOICE_CPP_ACCEL_LIB", "") or "").strip()

    candidates: list[Path] = []
    if env_library:
        candidates.append(Path(env_library))

    if os.name == "nt":
        library_names = ["voice_cpp_engine.dll"]
    elif os.name == "posix" and "darwin" in os.sys.platform:
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


def load_voice_cpp_backend() -> Optional[VoiceCppBackend]:
    global _backend_cache
    global _backend_attempted

    if not _is_cpp_accel_enabled():
        return None

    with _backend_lock:
        if _backend_attempted:
            return _backend_cache

        _backend_attempted = True
        for candidate in _candidate_library_paths():
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                _register_windows_dll_dirs([candidate.parent])
                library = ctypes.CDLL(str(candidate))
                _backend_cache = VoiceCppBackend(library=library, library_path=candidate)
                logger.info("Voice C++ acceleration loaded: %s", candidate)
                return _backend_cache
            except OSError as exc:
                logger.warning("Failed to load voice C++ acceleration (%s): %s", candidate, exc)
            except Exception as exc:
                logger.warning("Failed to initialize voice C++ backend (%s): %s", candidate, exc)

    return _backend_cache
