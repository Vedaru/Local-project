#!/usr/bin/env bash
# Project Local — 依赖安装（Linux/macOS）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "============================================"
echo "Project Local - 依赖安装"
echo "============================================"
python3 --version

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install "httpx[http2]" h2

if [[ "${1:-}" == "--with-torch" ]]; then
  python3 -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" \
    --index-url https://download.pytorch.org/whl/cu121 || \
  python3 -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" \
    --index-url https://download.pytorch.org/whl/cpu
fi

echo "安装完成。运行: ./scripts/start.sh"
