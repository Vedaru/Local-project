# 依赖与可复现构建

## 单一真相（Single Source of Truth）

| 用途 | 文件 | 说明 |
|------|------|------|
| **pip 安装（推荐）** | 根目录 [`requirements.txt`](../requirements.txt) | 已钉死版本，用于开发、CI 测试与安全扫描（`pip-audit`）。 |
| **包元数据与工具配置** | [`pyproject.toml`](../pyproject.toml) | PEP 621 `project` 段 + `[tool.poetry]` 用于 `poetry build` / Black / Ruff / mypy 等；**运行时依赖版本应与 `requirements.txt` 保持一致**。 |
| **可选：Poetry 锁文件** | `poetry.lock`（若使用 Poetry 管理环境） | 在修改 `[tool.poetry.dependencies]` 后执行 `poetry lock` 并提交，以锁定传递依赖。 |

## 维护流程

1. **修改依赖时**：先更新 `requirements.txt` 中的钉死版本，再将 `pyproject.toml` 里 `[tool.poetry.dependencies]` / `[tool.poetry.group.dev.dependencies]` 对齐到相同版本（或兼容范围的上界）。
2. **CI**：Lint 使用与 `requirements.txt` 中一致的 Black / isort / Ruff / mypy 版本；测试类 job 使用 `pip install -r requirements.txt`，确保与本地「全量安装」一致。
3. **不使用 Poetry 的开发者**：仅需 `python -m pip install -r requirements.txt`。

## pre-commit（可选）

仓库根目录提供 [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)，其中 Black / isort / Ruff 版本与 CI（[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)）一致。安装后执行：

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## pip-tools（可选）

若希望由「顶层依赖」自动生成完整 `requirements.txt`，可安装 `pip-tools`，维护 `requirements.in` 后执行：

```bash
pip-compile requirements.in -o requirements.txt
```

当前仓库以手工维护的 `requirements.txt` 为准；引入 `pip-compile` 时需团队约定并更新本页。
