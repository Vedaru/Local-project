"""
Unit tests for modules/config.py

Covers:
- AppConfig dataclass defaults
- load_config() with mocked env/yaml
- _clean_env_value() edge cases
- EnvironmentAwareConfig
- _to_int / _to_float helpers
"""

import os

# Ensure project root is in path
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import under test (re-export layer — still has all symbols)
import modules.config as config_module

# Also import the base for direct path patching in legacy tests
from modules import config_base  # noqa: E402

# ============================================================
# Tests for helper functions
# ============================================================


class TestCleanEnvValue:
    def test_none_returns_none(self):
        assert config_module._clean_env_value(None) is None

    def test_empty_string(self):
        assert config_module._clean_env_value("") == ""  # returns "", not None

    def test_strips_whitespace(self):
        assert config_module._clean_env_value("  hello  ") == "hello"

    def test_removes_surrounding_quotes(self):
        assert config_module._clean_env_value('"hello"') == "hello"
        assert config_module._clean_env_value("'hello'") == "'hello'"  # only double quotes removed

    def test_plain_value(self):
        assert config_module._clean_env_value("my-value") == "my-value"


class TestToInt:
    def test_valid_int(self):
        assert config_module._to_int("42", 0) == 42

    def test_invalid_returns_default(self):
        assert config_module._to_int("abc", 10) == 10

    def test_none_returns_default(self):
        assert config_module._to_int(None, 5) == 5

    def test_negative_int(self):
        assert config_module._to_int("-3", 0) == -3


class TestToFloat:
    def test_valid_float(self):
        result = config_module._to_float("3.14", 0.0)
        assert abs(result - 3.14) < 0.001

    def test_invalid_returns_default(self):
        assert config_module._to_float("abc", 2.5) == 2.5

    def test_none_returns_default(self):
        assert config_module._to_float(None, 1.0) == 1.0


# ============================================================
# Tests for EnvironmentAwareConfig
# ============================================================


class TestEnvironmentAwareConfig:
    @patch.dict(os.environ, {}, clear=True)
    def test_default_development_mode(self):
        env_cfg = config_module.EnvironmentAwareConfig()
        assert env_cfg.environment == "development"
        assert "project_config.yaml" in env_cfg.get_config_path()

    @patch.dict(os.environ, {"APP_ENV": "production"})
    def test_production_mode(self):
        env_cfg = config_module.EnvironmentAwareConfig()
        assert env_cfg.environment == "production"

    @patch.dict(os.environ, {"APP_CONFIG_PATH": "/custom/path.yaml"})
    def test_explicit_path_takes_precedence(self):
        env_cfg = config_module.EnvironmentAwareConfig()
        assert env_cfg.get_config_path() == "/custom/path.yaml"


# ============================================================
# Tests for AppConfig
# ============================================================


class TestAppConfigDefaults:
    def test_default_values_are_sensible(self):
        cfg = config_module.AppConfig()
        assert cfg.project_root != ""
        assert cfg.sovits_url != ""
        assert cfg.avatar_width > 0
        assert cfg.avatar_height > 0
        assert cfg.ear_enabled is True
        assert cfg.agent_max_steps > 0
        assert isinstance(cfg.controller_app_whitelist, dict)

    def test_custom_values(self):
        cfg = config_module.AppConfig(
            model_name="test-model",
            avatar_width=800,
            avatar_height=600,
            ear_enabled=False,
        )
        assert cfg.model_name == "test-model"
        assert cfg.avatar_width == 800
        assert cfg.ear_enabled is False


class TestLoadConfig:
    """Test load_config with mocked filesystem and env."""

    @pytest.fixture
    def mock_env_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Set up temporary .env and config.yaml for testing."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            'ARK_API_KEY="test-key-123"\n'
            "MODEL_NAME=test-model\n"
            'SYSTEM_PROMPT="You are a test assistant."\n',
            encoding="utf-8",
        )

        yaml_file = tmp_path / "config.yaml"
        yaml_data = {
            "api": {"sovits_url": "http://test:9999"},
            "audio": {
                "ref_audio_path": "test.wav",
                "prompt_text": "test prompt",
                "sample_rate": 44100,
            },
            "memory": {
                "data_dir": "test_memory",
                "collection_name": "test_collection",
            },
            "logging": {"log_dir": "test_logs"},
            "controller": {
                "enabled": True,
                "failsafe": False,
                "app_whitelist": {"chrome": "Chrome"},
            },
            "agent": {"max_steps": 50, "task_timeout_seconds": 120.0},
            "ear": {"enabled": False, "model_size": "small"},
        }
        yaml_file.write_text(yaml.dump(yaml_data), encoding="utf-8")
        # After split: load_config() accepts explicit env_path/config_path params,
        # no need to monkeypatch internal module attributes.
        return env_file, yaml_file

    def test_loads_api_keys_from_env(self, mock_env_files):
        # After split: load_config accepts explicit env_path/config_path params
        cfg = config_module.load_config(env_path=str(mock_env_files[0]), config_path=str(mock_env_files[1]))
        assert cfg.ark_api_key == "test-key-123"
        assert cfg.model_name == "test-model"
        assert cfg.system_prompt == "You are a test assistant."

    def test_loads_yaml_settings(self, mock_env_files):
        cfg = config_module.load_config(config_path=str(mock_env_files[1]))
        assert cfg.sovits_url == "http://test:9999"
        assert cfg.audio_sample_rate == 44100
        assert cfg.memory_collection_name == "test_collection"
        assert cfg.controller_enabled is True
        assert cfg.controller_failsafe is False
        assert cfg.agent_max_steps == 50
        assert cfg.ear_enabled is False

    def test_missing_yaml_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        nonexistent = tmp_path / "nonexistent.yaml"
        cfg = config_module.load_config(config_path=str(nonexistent))
        assert cfg.model_name is None or isinstance(cfg.model_name, str)


# ============================================================
# Tests for _ClientProxy lazy initialization
# ============================================================


class TestClientProxy:
    def test_proxy_defers_client_creation(self):
        from modules.config_legacy import _ClientProxy

        # Should not raise even without real API key — just verify it's a proxy object
        proxy = _ClientProxy()
        assert hasattr(proxy, "__getattr__")

    @patch("modules.config_legacy._get_client")
    def test_proxy_delegates_getattr(self, mock_get_client):
        from unittest.mock import MagicMock

        from modules.config_legacy import _ClientProxy

        mock_client_instance = MagicMock()
        mock_client_instance.chat = "chat_attr"
        mock_get_client.return_value = mock_client_instance

        proxy = _ClientProxy()
        result = proxy.chat  # triggers __getattr__ → _get_client()
        assert result == "chat_attr"  # MagicMock returns the attr value we set
        mock_get_client.assert_called_once()


def test_config_all_exports_are_available():
    missing = [name for name in config_module.__all__ if not hasattr(config_module, name)]
    assert missing == []

