# 开发者贡献指南

**Language / 言語 / 语言:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

本文档说明如何在本项目中进行开发、测试与提交流程。

## 1. 开发环境

### 前置要求

- Python 3.10 - 3.11（推荐）
- Git
- Rust 工具链（仅在修改 `rust_modules/web_fetcher_rs` 时需要）
- C++/CMake 工具链（仅在修改 `cpp_modules/voice_cpp_engine` 时需要）

### 初始化

```powershell
git clone https://github.com/CHANGE_ME/local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

推荐脚本入口（Windows）：`scripts\install.bat`、`scripts\start.bat`、`scripts\check.bat`。根目录同名 `.bat` 为兼容包装。

Docker 后端栈：`docker compose -f docker/docker-compose.yml up -d` 或 `make docker-up`。

配置分层见 `config/` 目录与 [`DEPENDENCIES.md`](DEPENDENCIES.md)。

## 代码组织约定

- 新增业务模块优先保持 **300–500 行** 量级，职责单一；已有大文件（如 `modules/voice.py`、`modules/memory/core.py`、`microservices/orchestrator/core.py`）仅在明确拆分时重构，不强制为凑行数而拆分。
- 文件名统一使用 **snake_case**（Python 模块）或与现有目录一致的小写命名。
- Vendor 目录（`modules/gpt_sovits`、`modules/openmanus`）以同步上游为主，避免大规模格式化。

## 2. 本地运行与测试

```powershell
python main.py
```

```powershell
python -m pytest -q
```

建议在改动 OpenManus 工具链后，至少执行：

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## 3. Rust 抓取扩展开发流程

当你修改以下目录时：

- `rust_modules/web_fetcher_rs`
- `modules/openmanus/app/tool/web_search.py`

请同步执行 Rust 扩展构建与回归测试：

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
```

可选原生检查：

```powershell
cargo check --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

## 4. C++ 语音加速开发流程

当你修改以下目录时：

- `cpp_modules/voice_cpp_engine`
- `modules/voice.py`
- `modules/voice_cpp_accel.py`

请同步执行 C++ 库构建与语音回归测试：

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
python -m pytest tests/test_voice_tts_chain.py -q
python -m pytest tests/test_voice_service_wav_cleanup.py -q
```

## 5. Tool 调度并发策略

`ToolCollection` 已支持批量与并发执行（`execute_many`）。

默认串行工具（请保持谨慎）：

- `python_execute`
- `str_replace_editor`
- `file_operator`
- `terminate`
- `browser_use`
- `tool_selector`

新增有副作用的工具时，请先评估是否应加入串行名单。

相关环境变量：

- `OPENMANUS_TOOL_PARALLEL_ENABLED`：是否启用并发
- `OPENMANUS_TOOL_PARALLEL_MAX`：最大并发数

## 6. 文档同步要求

涉及架构、运行方式、性能策略变更时，请同步更新以下 6 份文档：

- `docs/README.md`
- `docs/README_EN.md`
- `docs/README_JA.md`
- `docs/CONTRIBUTING.md`
- `docs/CONTRIBUTING_EN.md`
- `docs/CONTRIBUTING_JA.md`

## 7. 提交流程

1. 创建分支：`git checkout -b feat/your-topic`
2. 开发并提交改动
3. 确认测试通过
4. 发起 Pull Request

提交信息建议：

```text
<type>: <summary>
```

常用 `type`：

- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`

## 8. PR 检查清单

- [ ] 代码改动与目标一致
- [ ] 至少执行了相关回归测试
- [ ] 没有引入明显性能回退
- [ ] 中英日文档已同步（如适用）
- [ ] 提交信息清晰可读
