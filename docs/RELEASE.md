# 发版流程（惯例）

在发布到 PyPI 或打 GitHub Release 前建议完成以下步骤。

## 版本号

- **Python 包版本**：与 [`pyproject.toml`](../pyproject.toml) 中 `[project]` / `[tool.poetry]` 的 `version` 保持一致。
- **Git 标签**：使用语义化版本标签，例如 `v0.1.0`，与上述版本号对应（带 `v` 前缀）。

## 发布前检查

1. 将 [`CHANGELOG.md`](../CHANGELOG.md) 中 `[Unreleased]` 的内容整理为带日期的版本小节（如 `## [0.1.0] - YYYY-MM-DD`），并新开空的 `[Unreleased]`。
2. 若仓库已公开：将 [`pyproject.toml`](../pyproject.toml) 中 `[project.urls]` 的 `Homepage` / `Repository` 设为真实地址（参见 [`METADATA.md`](METADATA.md) 中的占位符说明）。
3. 运行本地校验：`python -m pytest`、`python -m mypy modules/ microservices/ main.py application.py`（与 CI 一致）。

## 与 CI 的衔接

合并到默认分支后，确认 GitHub Actions 中 **CI** workflow 全部通过再打标签或发布。
