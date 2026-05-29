#!/usr/bin/env bash
# Project Local — 启动微服务栈 + GUI（Linux/macOS）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export CT2_USE_CUDA="${CT2_USE_CUDA:-0}"

start_service() {
  local name="$1"
  local module="$2"
  local port="$3"
  python3 -m uvicorn "$module" --host 127.0.0.1 --port "$port" &
  echo "[INFO] started $name on :$port (pid $!)"
}

if [[ "${1:-}" == "--start-services-only" ]]; then
  start_service memory-service microservices.memory_service.main:app 18082
  start_service agent-service microservices.agent_service.main:app 18083
  start_service voice-service microservices.voice_service.main:app 18084
  start_service orchestrator microservices.orchestrator.main:app 18081
  start_service gateway microservices.gateway.main:app 18080
  wait
  exit 0
fi

GW_URL="${MICROSERVICES_GATEWAY_URL:-http://127.0.0.1:18080}"
if ! curl -fsS "${GW_URL}/openapi.json" | grep -q '/v1/chat'; then
  echo "[WARN] 网关不可用，正在启动微服务栈..."
  start_service memory-service microservices.memory_service.main:app 18082
  start_service agent-service microservices.agent_service.main:app 18083
  start_service voice-service microservices.voice_service.main:app 18084
  start_service orchestrator microservices.orchestrator.main:app 18081
  start_service gateway microservices.gateway.main:app 18080
  sleep 5
fi

python3 main.py
