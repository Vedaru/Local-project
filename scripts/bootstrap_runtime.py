"""Bootstrap project-local embeddable Python under runtime/.

Uses scripts/runtime_version.txt (must match pyproject requires-python / tool.python_version).
Does not use Conda or PATH Python for installation — only for optional re-run of this script.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
VERSION_FILE = SCRIPT_DIR / "runtime_version.txt"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def read_pinned_version() -> str:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", raw):
        raise ValueError(f"Invalid runtime pin in {VERSION_FILE}: {raw!r}")
    return raw


def embed_zip_name(version: str) -> str:
    return f"python-{version}-embed-amd64.zip"


def pth_filename(version: str) -> str:
    major, minor, _ = version.split(".")
    return f"python{major}{minor}._pth"


def embed_download_url(version: str) -> str:
    return f"https://www.python.org/ftp/python/{version}/{embed_zip_name(version)}"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[runtime] download {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    dest.write_bytes(data)


def configure_pth(runtime_dir: Path, version: str) -> Path:
    pth_path = runtime_dir / pth_filename(version)
    if not pth_path.exists():
        raise FileNotFoundError(f"Missing embed path file: {pth_path}")
    major, minor, _ = version.split(".")
    zip_stem = f"python{major}{minor}"
    lines = [
        f"{zip_stem}.zip",
        ".",
        "..",
        "import site",
    ]
    pth_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[runtime] configured {pth_path.name}")
    return pth_path


def install_pip(python_exe: Path) -> None:
    get_pip = RUNTIME_DIR / "_get-pip.py"
    download(GET_PIP_URL, get_pip)
    print("[runtime] installing pip...")
    subprocess.run([str(python_exe), str(get_pip)], check=True, cwd=RUNTIME_DIR)
    get_pip.unlink(missing_ok=True)


def verify(python_exe: Path, expected_version: str) -> None:
    proc = subprocess.run(
        [str(python_exe), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = (proc.stdout or proc.stderr or "").strip()
    if expected_version not in out:
        raise RuntimeError(f"Unexpected version output: {out!r}")
    print(f"[runtime] OK {out}")


def bootstrap(*, force: bool = False) -> Path:
    version = read_pinned_version()
    python_exe = RUNTIME_DIR / "python.exe"

    if python_exe.exists() and not force:
        verify(python_exe, version)
        print(f"[runtime] already present: {python_exe}")
        return python_exe

    if RUNTIME_DIR.exists() and force:
        shutil.rmtree(RUNTIME_DIR)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    zip_path = RUNTIME_DIR / embed_zip_name(version)
    if not zip_path.exists():
        download(embed_download_url(version), zip_path)

    print(f"[runtime] extracting {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(RUNTIME_DIR)
    zip_path.unlink(missing_ok=True)

    configure_pth(RUNTIME_DIR, version)
    install_pip(python_exe)
    verify(python_exe, version)
    return python_exe


def main() -> int:
    parser = argparse.ArgumentParser(description="Install embeddable Python into runtime/")
    parser.add_argument("--force", action="store_true", help="Reinstall runtime from scratch")
    args = parser.parse_args()
    try:
        bootstrap(force=args.force)
    except Exception as exc:
        print(f"[runtime] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
