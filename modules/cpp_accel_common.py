"""
C++ 加速桥接公共工具

提供 DLL 搜索路径注册、候选库路径发现等共享逻辑，
供 memory_cpp_accel 和 voice_cpp_accel 复用。
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from .logging_config import get_logger

logger = get_logger("cpp_accel_common")

# ---- ctypes 公共辅助 ----

_PY_BYTES_AS_STRING = ctypes.pythonapi.PyBytes_AsString
_PY_BYTES_AS_STRING.argtypes = [ctypes.py_object]
_PY_BYTES_AS_STRING.restype = ctypes.c_void_p


def as_bytes_pointer(data: bytes) -> tuple[object, object]:
    """将 bytes 对象转为 ctypes uint8 指针，返回 (pointer, keepalive)。"""
    if not data:
        return ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_uint8)), data
    address = int(_PY_BYTES_AS_STRING(data))
    pointer = ctypes.cast(address, ctypes.POINTER(ctypes.c_uint8))
    return pointer, data


def as_uint8_pointer(data: bytes | bytearray) -> tuple[object, object]:
    """将 bytes/bytearray 对象转为 ctypes uint8 指针，返回 (pointer, keepalive)。"""
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

    raise TypeError("buffer must be bytes or bytearray")


# ---- Windows DLL 目录注册（去重） ----

_windows_dll_handles: list[object] = []
_windows_dll_dirs_seen: set[str] = set()
_dll_dirs_lock = threading.Lock()


def register_windows_dll_dirs(extra_dirs: list[Path]) -> None:
    """将候选 DLL 目录注册到 Windows DLL 搜索路径，去重且线程安全。"""
    if os.name != "nt":
        return

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return

    with _dll_dirs_lock:
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


# ---- 候选库路径发现 ----


def candidate_library_paths(
    library_name: str,
    env_var_name: str,
    module_name: str,
    explicit_library: str = "",
) -> list[Path]:
    """
    通用候选库路径发现。

    Args:
        library_name: 库文件名 (如 "memory_cpp_engine.dll")
        env_var_name: 环境变量名 (如 "MEMORY_CPP_ACCEL_LIB")
        module_name: 子模块目录名 (如 "memory_cpp_engine")
        explicit_library: 显式指定的库路径
    """
    root_dir = Path(__file__).resolve().parents[1]
    explicit_library = (explicit_library or "").strip()
    env_library = (os.getenv(env_var_name, "") or "").strip()

    candidates: list[Path] = []
    if explicit_library:
        candidates.append(Path(explicit_library))
    if env_library:
        candidates.append(Path(env_library))

    if os.name == "nt":
        library_names = [library_name]
    elif os.name == "posix" and "darwin" in sys.platform:
        base = library_name.rsplit(".", 1)[0]
        library_names = [f"{base}.dylib", f"lib{base}.dylib"]
    else:
        base = library_name.rsplit(".", 1)[0]
        library_names = [f"{base}.so", f"lib{base}.so"]

    search_dirs = [
        root_dir / "build" / module_name,
        root_dir / "build" / module_name / "Release",
        root_dir / "build" / module_name / "Debug",
        root_dir / "cpp_modules" / module_name / "build",
        root_dir / "cpp_modules" / module_name / "build" / "Release",
        root_dir / "cpp_modules" / module_name / "build" / "Debug",
    ]

    for search_dir in search_dirs:
        for lib_name in library_names:
            candidates.append(search_dir / lib_name)

    deduplicated: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)

    return deduplicated


# ---- 通用后端加载器 ----


def load_cpp_backend_common(
    *,
    library_name: str,
    env_var_name: str,
    module_name: str,
    backend_factory,
    explicit_library: str = "",
    logger_name: str = "cpp_accel",
    required: bool = False,
) -> Optional[object]:
    """
    通用 C++ 后端加载逻辑。

    Args:
        library_name: 库文件名
        env_var_name: 环境变量名
        module_name: 子模块目录名
        backend_factory: 接受 (library, library_path) 返回 backend 的工厂函数
        explicit_library: 显式指定的库路径
        logger_name: 日志前缀
        required: 是否为必需（失败时是否抛异常）
    """
    mod_logger = get_logger(logger_name)

    candidates = candidate_library_paths(
        library_name=library_name,
        env_var_name=env_var_name,
        module_name=module_name,
        explicit_library=explicit_library,
    )

    errors: list[str] = []
    attempted_paths: list[str] = []

    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        attempted_paths.append(str(candidate))
        try:
            register_windows_dll_dirs([candidate.parent])
            library = ctypes.CDLL(str(candidate))
            backend = backend_factory(library=library, library_path=candidate)
            mod_logger.info("C++ acceleration loaded: %s", candidate)
            return backend
        except OSError as exc:
            mod_logger.warning("Failed to load C++ acceleration (%s): %s", candidate, exc)
            errors.append(f"{candidate}: {exc}")
        except Exception as exc:
            mod_logger.warning("Failed to initialize C++ backend (%s): %s", candidate, exc)
            errors.append(f"{candidate}: {exc}")

    if attempted_paths:
        detail = "; ".join(errors) if errors else "no successful candidate"
        error_msg = (
            f"C++ acceleration backend ({library_name}) failed to load. "
            f"Tried {len(attempted_paths)} path(s): {', '.join(attempted_paths)}. "
            f"Details: {detail}"
        )
    else:
        error_msg = f"C++ acceleration backend ({library_name}) library file was not found in candidate paths."

    if required:
        raise RuntimeError(error_msg)

    mod_logger.warning(error_msg)
    return None
