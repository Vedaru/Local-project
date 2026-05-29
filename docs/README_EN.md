<div align="center">

**🌐 Language / 语言 / 言語**

[![中文](https://img.shields.io/badge/中文-简体-red?style=flat-square)](README.md)
[![English](https://img.shields.io/badge/English-blue?style=flat-square)](README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-green?style=flat-square)](README_JA.md)

---

# 🤖 Project Local

**A local-first AI desktop assistant with virtual avatar support**

Voice interaction · Memory system · Tool calling · 3D Avatar · Microservices orchestration

</div>

---

## Overview

Project Local combines LLM dialogue, speech pipeline, memory management, desktop control, and avatar rendering in one local-first stack.
The default runtime path is microservices-only: GUI calls gateway, which routes to orchestrator and backend services.

## Core Capabilities

- Smart conversation with multi-turn context and tool calls.
- Speech chain with ASR + TTS.
- Memory layers with preference updates.
- Avatar expression and lip-sync rendering.
- Extensible tool ecosystem (file ops, web search/fetch, Python execution).

## Performance Acceleration (Updated)

### 1) Rust Web Fetcher Acceleration

- Path: `rust_modules/web_fetcher_rs`
- Added API: `fetch_content_batch(urls, timeout, max_chars)`.
- Python integration: `WebContentFetcher` now prefers Rust batch fetch and keeps safe fallback behavior.
- Optimization: shared HTTP client reuse in Rust to reduce per-request overhead.

### 2) Global Agent Tool Dispatch Acceleration

- Path: `modules/openmanus/app/tool/tool_collection.py`
- Added capabilities:
  - cached `to_params()` results
  - batched execution with `execute_many()`
  - bounded parallel scheduling
  - runtime execution stats via `get_stats()`
- Agent integration: `modules/openmanus/app/agent/toolcall.py` now executes tool calls in batch flow.

### 3) C++ Voice Generation Pipeline Acceleration

- Paths: `cpp_modules/voice_cpp_engine`, `modules/voice.py`, `modules/voice_cpp_accel.py`
- Added capabilities:
  - C++ audio chunk-index API: `build_chunk_index_cpp(total_size, chunk_size, ...)`
  - `tts_worker` now prefers C++ chunk splitting in cache-hit and buffered-fallback paths
  - Python chunk-splitting fallback is kept for backward compatibility and resilience
- Metrics: new counters `cpp_chunk_accel_success` and `cpp_chunk_accel_errors` for acceleration hit-rate tracking.

### Parallelism Controls

| Env Var | Default | Description |
|---|---|---|
| `OPENMANUS_TOOL_PARALLEL_ENABLED` | `1` | Enable parallel tool scheduling |
| `OPENMANUS_TOOL_PARALLEL_MAX` | `4` | Maximum concurrent tool calls |
| `WEB_FETCHER_RS_PY_EXT` | empty | Optional explicit path to Rust extension `.pyd/.so` |

The following tools stay serial by default for safety:
`python_execute`, `str_replace_editor`, `file_operator`, `terminate`, `browser_use`, `tool_selector`.

## Quick Start

### Option 1: Windows Batch Scripts (Recommended)

```batch
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

REM Install core dependencies
scripts\install.bat

REM Start the project
scripts\start.bat
```

Optional runtime check: `scripts\check.bat`

### Option 4: Docker (backend stack only)

```powershell
copy docker\.env.example docker\.env
docker compose -f docker/docker-compose.yml up -d
make docker-up
```

**Installation Parameters:**

| Parameter | Description |
|-----------|-------------|
| `-Dev` | Install development/testing dependencies |
| `-Mirror` | Use Tsinghua mirror for faster downloads |
| `-Torch` | Install PyTorch (CUDA 12.1) |
| `-GptSovits` | Install GPT-SoVITS voice synthesis dependencies |
| `-Optional` | Install optional dependencies (Docker, AWS, crawlers, etc.) |
| `-All` | Install all dependencies |

### Option 2: System Python / Virtual Environment

```powershell
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1

REM Install core dependencies
python -m pip install -r requirements.txt

REM Install PyTorch (requires >=2.6.0, choose based on CUDA version)
python -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/cu121

REM Install GPT-SoVITS dependencies (optional)
python -m pip install transformers huggingface_hub peft librosa soundfile pypinyin cn2an

python main.py
```

### Option 3: Poetry

```powershell
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

poetry install
poetry run python main.py
```

## Optional: Build Rust Fetcher Extension

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

If you use a custom toolchain, ensure Rust/Cargo and Python ABI are compatible.

## Optional: Build C++ Voice Acceleration Library

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
```

## Testing

```powershell
python -m pytest -q
```

Key regression suites:

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## Repository Layout

```text
Local-project/
├── config/                      # Layered YAML (default / dev / prod)
├── docker/                      # Docker images and compose
├── scripts/                     # install / start / check scripts
├── modules/                     # Core business modules
├── microservices/               # FastAPI services
├── assets/                      # Avatar models and audio refs
├── tests/
└── docs/
```

## Related Docs

- Chinese Developer Guide: `CONTRIBUTING.md`
- English Developer Guide: `CONTRIBUTING_EN.md`
- Japanese Developer Guide: `CONTRIBUTING_JA.md`

## License

MIT. See `../LICENSE`.
