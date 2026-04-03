# 开发者指南

**Language / 言語 / 语言:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

本文档介绍如何设置开发环境、运行测试以及贡献代码到 Local-project。

## 目录

- [开发环境设置](#开发环境设置)
- [项目结构](#项目结构)
- [代码规范](#代码规范)
- [测试](#测试)
- [CI/CD](#cicd)
- [模块说明](#模块说明)

## 开发环境设置

### 前置条件

- Python 3.9 - 3.11
- pip 或 Poetry
- Git

### 快速开始

```powershell
# 1. 克隆仓库
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. 安装依赖
.\dev.ps1 setup

# 4. 设置 pre-commit hooks
.\dev.ps1 pre-commit
```

### 使用 Poetry（推荐）

```powershell
# 安装 Poetry
pip install poetry

# 安装所有依赖
poetry install

# 激活虚拟环境
poetry shell
```

## 项目结构

```
Local-project/
├── modules/              # 核心模块
│   ├── agent/           # AI Agent 模块
│   ├── avatar/          # 虚拟形象模块
│   ├── memory/          # 记忆系统
│   ├── config.py        # 配置管理
│   ├── health.py        # 健康检查
│   ├── llm.py           # LLM 调用
│   ├── resilience.py    # 错误处理与重试
│   ├── utils.py         # 工具函数
│   └── voice.py         # 语音合成
├── microservices/       # 微服务框架（gateway/orchestrator/各服务）
├── tests/               # 测试文件
├── assets/              # 静态资源
├── data/                # 数据目录
├── dev.ps1              # 开发脚本入口
├── start_microservices_with_monitor.ps1  # 微服务启动脚本
├── .github/workflows/   # CI/CD 配置
├── main.py              # 主入口
├── pyproject.toml       # 项目配置
└── requirements.txt     # 依赖列表
```

## 代码规范

### 格式化

项目使用以下工具保持代码风格一致：

- **Black**: 代码格式化（行宽 120）
- **isort**: 导入排序
- **Ruff**: 快速 Python linter

```powershell
# 格式化代码
.\dev.ps1 format

# 或手动运行
black modules/ tests/ main.py
isort modules/ tests/ main.py
```

### 类型提示

推荐使用类型提示，并使用 mypy 进行检查：

```python
def process_text(text: str, max_length: int = 100) -> Optional[str]:
    """处理文本并返回结果"""
    if not text:
        return None
    return text[:max_length]
```

```powershell
# 类型检查
mypy modules/ --ignore-missing-imports
```

### Pre-commit Hooks

提交前会自动运行检查：

```powershell
# 安装 hooks
pre-commit install

# 手动运行所有检查
pre-commit run --all-files
```

## 测试

### 运行测试

```powershell
# 运行所有测试
.\dev.ps1 test

# 或直接使用 pytest
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_utils.py -v

# 运行特定测试
pytest tests/test_utils.py::TestCleanText::test_clean_text_preserves_chinese -v
```

### 测试覆盖率

```powershell
# 生成覆盖率报告
.\dev.ps1 test-cov

# 查看 HTML 报告
start htmlcov/index.html
```

### 编写测试

测试文件放在 `tests/` 目录下，命名格式为 `test_<module>.py`：

```python
# tests/test_example.py
import pytest
from modules.example import my_function

class TestMyFunction:
    """Tests for my_function."""
    
    def test_basic_case(self):
        """Test basic functionality."""
        result = my_function("input")
        assert result == "expected"
    
    @pytest.mark.slow
    def test_slow_operation(self):
        """Test that takes a long time."""
        # 标记为 slow，默认跳过
        pass
```

### 测试标记

- `@pytest.mark.slow` - 慢速测试（使用 `--runslow` 运行）
- `@pytest.mark.integration` - 集成测试（使用 `--runintegration` 运行）
- `@pytest.mark.unit` - 单元测试

## CI/CD

项目使用 GitHub Actions 进行持续集成：

### CI 流程

1. **代码质量检查** - Black, isort, Ruff, mypy
2. **单元测试** - 在多个 Python 版本和操作系统上运行
3. **覆盖率报告** - 上传到 Codecov
4. **安全扫描** - Bandit, pip-audit

### 本地验证

在提交前运行完整检查：

```powershell
.\dev.ps1 check
```

## 模块说明

### resilience.py - 错误处理与重试

提供统一的错误处理机制：

```python
from modules.resilience import retry, RetryStrategy, CircuitBreaker

# 使用重试装饰器
@retry(max_retries=3, strategy=RetryStrategy.EXPONENTIAL)
def call_external_api():
    # API 调用
    pass

# 使用断路器
breaker = CircuitBreaker(failure_threshold=5)

@breaker
def risky_operation():
    # 可能失败的操作
    pass
```

### health.py - 健康检查

监控关键服务状态：

```python
from modules.health import health_checker, check_sovits_health

# 注册健康检查
health_checker.register("sovits", check_sovits_health)

# 执行检查
result = health_checker.check("sovits")
print(f"Status: {result.status}")

# 检查所有服务
health = health_checker.check_all()
print(f"Overall: {health.overall_status}")
```

### microservices - 微服务启动与编排

项目运行时已迁移为微服务模式：

```batch
run_with_runtime.bat
```

说明：
- GUI 通过网关调用 orchestrator 与后端服务
- 服务地址、端口、鉴权参数统一由 microservices 下配置管理

## 贡献指南

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 提交消息规范

```
<type>: <description>

[optional body]
```

类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

