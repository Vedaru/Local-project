"""
Pytest configuration and fixtures for Local-project tests.

This module provides shared fixtures and configuration for all tests.
"""

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Install stubs for optional dependencies
from tests.stubs import install_all_stubs

install_all_stubs()

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir(project_root: Path) -> Path:
    """Return the test data directory, creating it if necessary."""
    test_data = project_root / "tests" / "data"
    test_data.mkdir(parents=True, exist_ok=True)
    return test_data


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Set up mock environment variables for testing."""
    env_vars = {
        "ARK_API_KEY": "test-api-key",
        "MODEL_NAME": "test-model",
        "SYSTEM_PROMPT": "You are a helpful assistant.",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def mock_openai_client() -> Generator[MagicMock, None, None]:
    """Mock the OpenAI client for testing without API calls."""
    with patch("openai.OpenAI") as mock_client:
        instance = MagicMock()
        mock_client.return_value = instance

        # Mock chat completion response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        instance.chat.completions.create.return_value = mock_response

        yield instance


@pytest.fixture
def sample_text() -> str:
    """Provide sample text for testing."""
    return "大家好，这是一段测试文本。"


@pytest.fixture
def sample_memory_data() -> dict:
    """Provide sample memory data for testing."""
    return {
        "user_input": "你好，我叫张三",
        "ai_response": "你好张三！很高兴认识你。",
        "entities": ["张三"],
        "timestamp": "2024-01-01T12:00:00",
    }


# ============================================================
# Test Markers Configuration
# ============================================================


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "requires_api: marks tests that require API access")
    config.addinivalue_line("markers", "requires_gpu: marks tests that require GPU")


# ============================================================
# Test Collection Hooks
# ============================================================


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers."""
    # Skip slow tests unless --runslow is passed
    if not config.getoption("--runslow", default=False):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)

    # Skip integration tests unless --runintegration is passed
    if not config.getoption("--runintegration", default=False):
        skip_integration = pytest.mark.skip(reason="need --runintegration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests",
    )
    parser.addoption(
        "--runintegration",
        action="store_true",
        default=False,
        help="run integration tests",
    )
