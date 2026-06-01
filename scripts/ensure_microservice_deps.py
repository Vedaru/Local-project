"""Ensure FastAPI/Starlette versions match before starting microservices.

在 runtime 环境中若已安装 mcp/sse-starlette，Starlette 会停在 1.x，此时应升级 FastAPI>=0.128.6，
而不是强行降级 Starlette（pip 会装不上或装完仍被依赖拉回 1.x）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 项目根目录（scripts 的上一级）；单独运行本脚本时必须加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_project_on_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(root)

# Starlette 0.41.x 栈（无 Starlette 1.x 约束时）
PINNED_LEGACY = (
    "fastapi==0.115.12",
    "starlette==0.41.3",
    "uvicorn[standard]==0.32.1",
)

# Starlette 1.x 栈（与 mcp / sse-starlette 等兼容）
PINNED_MODERN = (
    "fastapi>=0.128.6,<0.136",
    "starlette>=1.0.0,<2.0.0",
    "uvicorn[standard]>=0.34.0,<0.37",
)


def _version_tuple(version: str) -> tuple[int, int]:
    try:
        parts = version.split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 0, 0


def _versions() -> tuple[str, str]:
    try:
        import fastapi
        import starlette
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        print(
            f"[preflight] missing package ({missing}). "
            "Run: scripts\\install.bat",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    return fastapi.__version__, starlette.__version__


def _is_compatible(fastapi_ver: str, starlette_ver: str) -> bool:
    sv = _version_tuple(starlette_ver)
    fv = _version_tuple(fastapi_ver)
    if sv >= (1, 0) and fv < (0, 128):
        return False
    if sv == (0, 41) and fv >= (0, 115):
        return True
    if sv < (1, 0) and fv >= (0, 104):
        return True
    if sv >= (1, 0) and fv >= (0, 128):
        return True
    return False


def _choose_repair_pins(starlette_ver: str) -> tuple[str, ...]:
    if _version_tuple(starlette_ver) >= (1, 0):
        return PINNED_MODERN
    return PINNED_LEGACY


def _pip_install(pins: tuple[str, ...]) -> tuple[int, str]:
    env = {**os.environ, "PYTHONNOUSERSITE": "1"}
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *pins,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode, tail[-1200:]


def _try_import_gateway() -> bool:
    try:
        from microservices.gateway.main import app  # noqa: F401

        _ = app
        return True
    except Exception as exc:
        print(f"[preflight] gateway import failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    _ensure_project_on_path()
    print(f"[preflight] python={sys.executable}")
    print(f"[preflight] project_root={PROJECT_ROOT}")
    fv, sv = _versions()
    print(f"[preflight] fastapi={fv} starlette={sv}")

    if not _is_compatible(fv, sv):
        return _repair_and_verify(fv, sv)

    if _try_import_gateway():
        print("[preflight] OK")
        return 0

    print(
        "[preflight] FastAPI/Starlette 版本已兼容，但无法导入 microservices.gateway。"
        " 请在项目根目录运行，或设置 PYTHONPATH=项目根目录。",
        file=sys.stderr,
    )
    return 1


def _repair_and_verify(fv: str, sv: str) -> int:
    strategies: list[tuple[str, ...]] = []
    primary = _choose_repair_pins(sv)
    strategies.append(primary)
    if primary != PINNED_MODERN:
        strategies.append(PINNED_MODERN)

    for idx, pins in enumerate(strategies, start=1):
        label = "modern (Starlette 1.x)" if pins == PINNED_MODERN else "legacy (Starlette 0.41.x)"
        print(f"[preflight] repair attempt {idx}: {label} ...", file=sys.stderr)
        code, tail = _pip_install(pins)
        if code != 0:
            print(tail, file=sys.stderr)
            continue
        fv, sv = _versions()
        print(f"[preflight] after repair: fastapi={fv} starlette={sv}")
        if _is_compatible(fv, sv) and _try_import_gateway():
            print("[preflight] OK")
            return 0

    print(
        "[preflight] still incompatible. Try:\n"
        f"  {sys.executable} -m pip install --upgrade {' '.join(PINNED_MODERN)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
