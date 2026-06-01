# Developer Contribution Guide

**Language / 言語 / 语言:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

This guide explains the recommended development, testing, and contribution workflow.

## 1. Development Environment

### Prerequisites

- Python 3.10 - 3.11 (recommended)
- Git
- Rust toolchain (required only when changing `rust_modules/web_fetcher_rs`)
- C++/CMake toolchain (required only when changing `cpp_modules/voice_cpp_engine`)

### Setup

```powershell
git clone https://github.com/Vedaru/Local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Run and Test Locally

```powershell
python main.py
```

```powershell
python -m pytest -q
```

For OpenManus toolchain updates, run at least:

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## 3. Rust Fetcher Extension Workflow

When changing:

- `rust_modules/web_fetcher_rs`
- `modules/openmanus/app/tool/web_search.py`

build and verify the extension:

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
```

Optional native check:

```powershell
cargo check --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

## 4. C++ Voice Acceleration Workflow

When changing:

- `cpp_modules/voice_cpp_engine`
- `modules/voice.py`
- `modules/voice_cpp_accel.py`

build and verify the C++ library and voice regressions:

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
python -m pytest tests/test_voice_tts_chain.py -q
python -m pytest tests/test_voice_service_wav_cleanup.py -q
```

## 5. Tool Dispatch Parallelism Policy

`ToolCollection` supports batched and parallel dispatch via `execute_many`.

The following tools are serial-only by default:

- `python_execute`
- `str_replace_editor`
- `file_operator`
- `terminate`
- `browser_use`
- `tool_selector`

When adding a new side-effect tool, evaluate whether it must remain serial.

Relevant env vars:

- `OPENMANUS_TOOL_PARALLEL_ENABLED`: enable/disable parallel dispatch
- `OPENMANUS_TOOL_PARALLEL_MAX`: max concurrency

## 6. Documentation Sync Requirements

If architecture/runtime/performance behavior changes, update all six docs:

- `docs/README.md`
- `docs/README_EN.md`
- `docs/README_JA.md`
- `docs/CONTRIBUTING.md`
- `docs/CONTRIBUTING_EN.md`
- `docs/CONTRIBUTING_JA.md`

## 7. Contribution Flow

1. Create a branch: `git checkout -b feat/your-topic`
2. Implement and commit your change
3. Ensure tests pass
4. Open a Pull Request

Commit message format:

```text
<type>: <summary>
```

Common `type` values:

- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`

## 8. PR Checklist

- [ ] Change scope matches the goal
- [ ] Relevant regression tests were executed
- [ ] No obvious performance regression introduced
- [ ] CN/EN/JA docs updated when applicable
- [ ] Commit messages are clear
