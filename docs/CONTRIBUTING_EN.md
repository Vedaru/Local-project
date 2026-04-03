# Developer Guide

**Language / 語言 / 言語:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

This document describes how to set up the development environment, run tests, and contribute code to Local-project.

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Project Structure](#project-structure)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [CI/CD](#cicd)
- [Module Documentation](#module-documentation)

## Development Environment Setup

### Prerequisites

- Python 3.9 - 3.11
- pip or Poetry
- Git

### Quick Start

```powershell
# 1. Clone repository
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
.\dev.ps1 setup

# 4. Set up pre-commit hooks
.\dev.ps1 pre-commit
```

### Using Poetry (Recommended)

```powershell
# Install Poetry
pip install poetry

# Install all dependencies
poetry install

# Activate virtual environment
poetry shell
```

## Project Structure

```
Local-project/
├── modules/              # Core modules
│   ├── agent/           # AI Agent module
│   ├── avatar/          # Avatar module
│   ├── memory/          # Memory system
│   ├── config.py        # Configuration management
│   ├── health.py        # Health check
│   ├── llm.py           # LLM calls
│   ├── resilience.py    # Error handling & retry
│   ├── utils.py         # Utility functions
│   └── voice.py         # Voice synthesis
├── microservices/       # Microservices framework (gateway/orchestrator/services)
├── tests/               # Test files
├── assets/              # Static assets
├── data/                # Data directory
├── dev.ps1              # Development script entry
├── start_microservices_with_monitor.ps1  # Microservice startup script
├── .github/workflows/   # CI/CD configuration
├── main.py              # Main entry point
├── pyproject.toml       # Project configuration
└── requirements.txt     # Dependencies list
```

## Code Standards

### Formatting

The project uses the following tools to maintain consistent code style:

- **Black**: Code formatting (line width 120)
- **isort**: Import sorting
- **Ruff**: Fast Python linter

```powershell
# Format code
.\dev.ps1 format

# Or run manually
black modules/ tests/ main.py
isort modules/ tests/ main.py
```

### Type Hints

Type hints are recommended and checked with mypy:

```python
def process_text(text: str, max_length: int = 100) -> Optional[str]:
    """Process text and return result"""
    if not text:
        return None
    return text[:max_length]
```

```powershell
# Type check
mypy modules/ --ignore-missing-imports
```

### Pre-commit Hooks

Checks run automatically before commit:

```powershell
# Install hooks
pre-commit install

# Run all checks manually
pre-commit run --all-files
```

## Testing

### Running Tests

```powershell
# Run all tests
.\dev.ps1 test

# Or run directly with pytest
pytest tests/ -v

# Run specific test file
pytest tests/test_utils.py -v

# Run specific test
pytest tests/test_utils.py::TestCleanText::test_clean_text -v
```

### Test Coverage

```powershell
# Generate coverage report
.\dev.ps1 test-cov

# View HTML report
start htmlcov/index.html
```

### Writing Tests

Test files are placed in the `tests/` directory with naming format `test_<module>.py`:

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
        # Marked as slow, skipped by default
        pass
```

### Test Markers

- `@pytest.mark.slow` - Slow tests (run with `--runslow`)
- `@pytest.mark.integration` - Integration tests (run with `--runintegration`)
- `@pytest.mark.unit` - Unit tests

## CI/CD

The project uses GitHub Actions for continuous integration:

### CI Pipeline

1. **Code Quality Checks** - Black, isort, Ruff, mypy
2. **Unit Tests** - Run on multiple Python versions and operating systems
3. **Coverage Report** - Upload to Codecov
4. **Security Scan** - Bandit, pip-audit

### Local Verification

Run full checks before commit:

```powershell
.\dev.ps1 check
```

## Module Documentation

### resilience.py - Error Handling & Retry

Provides unified error handling mechanism:

```python
from modules.resilience import retry, RetryStrategy, CircuitBreaker

# Use retry decorator
@retry(max_retries=3, strategy=RetryStrategy.EXPONENTIAL)
def call_external_api():
    # API call
    pass

# Use circuit breaker
breaker = CircuitBreaker(failure_threshold=5)

@breaker
def risky_operation():
    # Operation that might fail
    pass
```

### health.py - Health Check

Monitor critical service status:

```python
from modules.health import health_checker, check_sovits_health

# Register health check
health_checker.register("sovits", check_sovits_health)

# Run check
result = health_checker.check("sovits")
print(f"Status: {result.status}")

# Check all services
health = health_checker.check_all()
print(f"Overall: {health.overall_status}")
```

### microservices - Service Startup and Orchestration

Runtime is fully migrated to microservices mode:

```batch
run_with_runtime.bat
```

Notes:
- GUI communicates with backend through gateway and orchestrator
- Service ports, URLs, and auth settings are managed under microservices config

## Contribution Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Create a Pull Request

### Commit Message Convention

```
<type>: <description>

[optional body]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation update
- `style`: Code formatting (no functional change)
- `refactor`: Refactoring
- `test`: Test-related
- `chore`: Build/tooling-related

