<div align="center">

**🌐 Language / 语言 / 言語**

[![中文](https://img.shields.io/badge/中文-简体-red?style=flat-square)](README.md)
[![English](https://img.shields.io/badge/English-blue?style=flat-square)](README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-green?style=flat-square)](README_JA.md)

---

# 🤖 Project Local

**一个支持虚拟形象的本地 AI 桌面助手**

语音对话 · 智能记忆 · 工具调用 · 3D Avatar · 微服务编排

</div>

---

## 项目简介

Project Local 以本地优先为原则，整合 LLM 对话、语音链路、记忆系统、电脑控制与 Avatar 展示能力。
当前默认运行模式为 microservices-only：GUI 通过 gateway 调用 orchestrator 与后端服务。

## 核心能力

- 智能对话：支持多轮上下文与工具调用。
- 语音交互：ASR + TTS 串联，支持本地化运行。
- 记忆系统：短期/长期记忆与偏好更新。
- 虚拟形象：表情与口型联动。
- 工具生态：文件操作、网页检索、Python 执行等。

## 性能加速（本次更新）

### 1) Rust 网页抓取加速

- 路径：`rust_modules/web_fetcher_rs`
- 新增能力：Rust 扩展提供批量抓取接口 `fetch_content_batch(urls, timeout, max_chars)`。
- Python 集成：`WebContentFetcher` 优先走 Rust 批量路径，并保持降级逻辑。
- 优化点：复用共享 HTTP Client，减少重复构建开销。

### 2) Agent Tool 全局调度加速

- 路径：`modules/openmanus/app/tool/tool_collection.py`
- 新增能力：
  - `to_params()` 结果缓存
  - `execute_many()` 批量执行
  - 有界并发执行（可配置）
  - 执行统计 `get_stats()`
- Agent 集成：`modules/openmanus/app/agent/toolcall.py` 使用批量执行路径。

### 3) C++ 语音生成链路加速

- 路径：`cpp_modules/voice_cpp_engine`、`modules/voice.py`、`modules/voice_cpp_accel.py`
- 新增能力：
  - C++ 音频分块索引接口 `build_chunk_index_cpp(total_size, chunk_size, ...)`
  - Python `tts_worker` 在缓存命中与缓冲回退路径下优先使用 C++ 分块
  - 保留 Python 分块回退，确保旧版库/异常场景不影响可用性
- 统计指标：新增 `cpp_chunk_accel_success`、`cpp_chunk_accel_errors`，用于观测分块加速命中率。

### 并发开关

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `OPENMANUS_TOOL_PARALLEL_ENABLED` | `1` | 是否启用并行 tool 调度 |
| `OPENMANUS_TOOL_PARALLEL_MAX` | `4` | 最大并发度 |
| `WEB_FETCHER_RS_PY_EXT` | 空 | 可选，指定 Rust 扩展 `.pyd/.so` 路径 |

说明：以下工具默认串行执行以保证安全性：
`python_execute`、`str_replace_editor`、`file_operator`、`terminate`、`browser_use`、`tool_selector`。

## 快速开始

### 方式一：Windows 独立 Runtime（推荐）

```batch
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

install_dependencies.bat
run_with_runtime.bat
```

可先执行：

```batch
check_runtime.bat
```

### 方式二：系统 Python / 虚拟环境

```powershell
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## 可选：构建 Rust 抓取扩展

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

如果你使用非默认工具链，请确保 Rust/Cargo 可用并与本地 Python ABI 匹配。

## 可选：构建 C++ 语音加速库

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
```

## 测试

```powershell
python -m pytest -q
```

关键回归用例：

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## 项目结构（节选）

```text
Local-project/
├── modules/                     # 主功能模块
├── microservices/               # 网关、编排器、服务
├── rust_modules/web_fetcher_rs/ # Rust 网页抓取扩展
├── tests/                       # 测试
└── docs/                        # 多语言文档
```

## 相关文档

- 中文开发指南：`CONTRIBUTING.md`
- English Developer Guide: `CONTRIBUTING_EN.md`
- 日本語開発ガイド：`CONTRIBUTING_JA.md`
- 依赖与可复现构建：[DEPENDENCIES.md](DEPENDENCIES.md)
- 安全与威胁面：[SECURITY.md](SECURITY.md)
- 健康检查与运维：[OPS_HEALTH.md](OPS_HEALTH.md)
- 仓库元数据（发布前替换占位 URL）：[METADATA.md](METADATA.md)

## 许可证

MIT，详见 [LICENSE](../LICENSE)。
