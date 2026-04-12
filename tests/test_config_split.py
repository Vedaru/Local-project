"""
Unit tests for the split config modules.

Covers:
- config_base.py: helpers, path constants, env loading
- config_app.py: AppConfig + load_config()
- config_tuning.py: TuningConfig + load_tuning() + get_tuning()
- config_legacy.py: backward-compatible constants
- config.py: re-export layer (backward compatibility)
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# Tests for config_base
# ============================================================


class TestConfigBase:
    """Tests for modules.config_base — path constants and helper functions."""

    def test_import_base(self):
        from modules.config_base import (
            CONFIG_PATH,
            ENV_PATH,
            GPT_SOVITS_ROOT,
            PROJECT_ROOT,
            TUNING_PATH,
            _clean_env_value,
            _env_int,
            _env_str,
            _read_bool,
            _to_float,
            _to_int,
        )
        assert isinstance(PROJECT_ROOT, str)
        assert len(PROJECT_ROOT) > 0
        assert isinstance(CONFIG_PATH, str)
        assert isinstance(ENV_PATH, str)

    def test_clean_env_value(self):
        from modules.config_base import _clean_env_value

        assert _clean_env_value(None) is None
        assert _clean_env_value("") == ""  # empty string returns empty string (not None)
        assert _clean_env_value("  hello  ") == "hello"
        assert _clean_env_value('"hello"') == "hello"
        assert _clean_env_value("my-value") == "my-value"

    def test_to_int(self):
        from modules.config_base import _to_int

        assert _to_int("42", 0) == 42
        assert _to_int("abc", 10) == 10
        assert _to_int(None, 5) == 5
        assert _to_int("-3", 0) == -3

    def test_to_float(self):
        from modules.config_base import _to_float

        assert abs(_to_float("3.14", 0.0) - 3.14) < 0.001
        assert _to_float("abc", 2.5) == 2.5

    def test_read_bool(self):
        from modules.config_base import _read_bool

        assert _read_bool("true") is True
        assert _read_bool("1") is True
        assert _read_bool("yes") is True
        assert _read_bool("false") is False
        assert _read_bool("0") is False
        assert _read_bool(None) is False
        assert _read_bool("", default=True) is True

    def test_env_str(self):
        from modules.config_base import _env_str

        with patch.dict(os.environ, {"TEST_VAR": "hello"}, clear=False):
            assert _env_str("TEST_VAR", "fallback") == "hello"

        # fallback when env not set
        assert _env_str("NONEXISTENT_VAR_xyz123", "default_val") == "default_val"

    def test_env_int_with_minimum(self):
        from modules.config_base import _env_int

        assert _env_int("NONEXISTENT", None, minimum=10) >= 10

    def test_get_yaml_config_returns_dict(self):
        from modules.config_base import get_yaml_config

        cfg = get_yaml_config()
        assert isinstance(cfg, dict)


# ============================================================
# Tests for config_app
# ============================================================


class TestConfigApp:
    """Tests for modules.config_app — AppConfig + load_config()."""

    def test_import_app(self):
        from modules.config_app import AppConfig, load_config

        assert AppConfig is not None
        assert callable(load_config)

    def test_default_values(self):
        from modules.config_app import AppConfig

        cfg = AppConfig()
        assert cfg.project_root != ""
        assert cfg.sovits_url != ""
        assert cfg.avatar_width > 0
        assert cfg.avatar_height > 0
        assert cfg.ear_enabled is True
        assert isinstance(cfg.controller_app_whitelist, dict)

    def test_secret_access_and_masked_repr(self):
        from modules.config_app import AppConfig

        cfg = AppConfig(ark_api_key="secret-key")
        assert cfg.get_api_key() == "secret-key"
        assert "secret-key" not in repr(cfg)

    def test_load_config_with_temp_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from modules.config_app import load_config

        env_file = tmp_path / ".env"
        env_file.write_text('ARK_API_KEY="test-key"\nMODEL_NAME=test\n', encoding="utf-8")

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            yaml.dump({
                "api": {"sovits_url": "http://test:9999"},
                "audio": {"sample_rate": 44100},
                "ear": {"enabled": False},
            }),
            encoding="utf-8",
        )

        cfg = load_config(env_path=str(env_file), config_path=str(yaml_file))
        assert cfg.ark_api_key == "test-key"
        assert cfg.get_api_key() == "test-key"
        assert cfg.model_name == "test"
        assert cfg.sovits_url == "http://test:9999"
        assert cfg.audio_sample_rate == 44100
        assert cfg.ear_enabled is False

    def test_sanitize_for_logging_masks_sensitive_fields(self):
        from modules.config_app import sanitize_for_logging

        payload = {
            "api_key": "abc",
            "nested": {"token": "def", "safe": "ok"},
        }
        masked = sanitize_for_logging(payload)
        assert masked["api_key"] == "***"
        assert masked["nested"]["token"] == "***"
        assert masked["nested"]["safe"] == "ok"


# ============================================================
# Tests for config_tuning
# ============================================================


class TestConfigTuning:
    """Tests for modules.config_tuning — TuningConfig + load_tuning() + get_tuning()."""

    def test_import_tuning(self):
        from modules.config_tuning import (
            ClientTuning,
            ExpressionTuning,
            GatewayTuning,
            OrchestratorTuning,
            ServicesTuning,
            TuningConfig,
            VoiceTuning,
            get_tuning,
            load_tuning,
        )
        assert all(v is not None for v in [
            TuningConfig, ServicesTuning, OrchestratorTuning,
            VoiceTuning, ExpressionTuning, GatewayTuning, ClientTuning,
            load_tuning, get_tuning,
        ])

    def test_default_values(self):
        from modules.config_tuning import TuningConfig

        t = TuningConfig()
        assert t.services.gateway_port == 18080
        assert t.orchestrator.memory_timeout_sec == 8.0
        assert t.voice.streaming_mode == 3
        assert t.expression.auto_reset_sec == 2.4
        assert t.client.user_id == "local-gui"

    def test_load_tuning_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from modules.config_tuning import load_tuning

        tuning_file = tmp_path / "tuning.yaml"
        tuning_file.write_text(
            yaml.dump({
                "services": {"gateway_port": 9000},
                "orchestrator": {"memory_timeout_sec": 15.0},
                "voice": {"connect_timeout_sec": 10},
            }),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "modules.config_tuning.TUNING_PATH",
            str(tuning_file),
        )
        t = load_tuning()
        assert t.services.gateway_port == 9000
        assert t.orchestrator.memory_timeout_sec == 15.0
        assert t.voice.connect_timeout_sec == 10

    def test_get_tuning_singleton(self):
        from unittest.mock import patch

        from modules.config_tuning import TuningConfig, get_tuning

        mock_cfg = TuningConfig()
        with patch("modules.config_tuning.load_tuning", return_value=mock_cfg):
            t1 = get_tuning()
            t2 = get_tuning()
            assert t1 is t2  # same singleton instance

    def test_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from modules.config_tuning import load_tuning

        tuning_file = tmp_path / "tuning.yaml"
        tuning_file.write_text(yaml.dump({"services": {"gateway_port": 8080}}), encoding="utf-8")
        monkeypatch.setattr("modules.config_tuning.TUNING_PATH", str(tuning_file))

        with patch.dict(os.environ, {"GATEWAY_PORT": "7777"}, clear=False):
            t = load_tuning()
            assert t.services.gateway_port == 7777  # env override wins


# ============================================================
# Tests for config_legacy
# ============================================================


class TestConfigLegacy:
    """Tests for modules.config_legacy — backward-compatible constants."""

    def test_import_legacy_constants(self):
        from modules.config_legacy import (
            CONTROLLER_ENABLED,
            EAR_ENABLED,
            EAR_MODEL_SIZE,
            GPT_SOVITS_PATH,
            MODEL_NAME,
            PROMPT_TEXT,
            REF_AUDIO,
            SOVITS_URL,
            SYSTEM_PROMPT,
            client,
        )
        assert SOVITS_URL.startswith("http")
        assert REF_AUDIO.endswith(".wav")
        assert isinstance(EAR_ENABLED, bool)
        assert EAR_MODEL_SIZE in ("tiny", "base", "small", "medium", "large")

    def test_client_proxy_exists(self):
        from modules.config_legacy import client

        assert hasattr(client, "__getattr__")


# ============================================================
# Tests for config.py re-export layer (backward compat)
# ============================================================


class TestConfigReexport:
    """Verify that modules.config still exports everything after the split."""

    def test_all_exports_available(self):
        import modules.config as cfg

        # Core classes/functions
        assert hasattr(cfg, "AppConfig")
        assert hasattr(cfg, "load_config")
        assert hasattr(cfg, "TuningConfig")
        assert hasattr(cfg, "load_tuning")
        assert hasattr(cfg, "get_tuning")

        # Legacy constants
        assert hasattr(cfg, "SOVITS_URL")
        assert hasattr(cfg, "MODEL_NAME")
        assert hasattr(cfg, "EAR_ENABLED")
        assert hasattr(cfg, "client")

        # Helpers
        assert hasattr(cfg, "_clean_env_value")
        assert hasattr(cfg, "_to_int")
        assert hasattr(cfg, "_env_int")

    def test_load_config_works_via_config(self):
        import modules.config as cfg

        c = cfg.load_config()
        assert isinstance(c, cfg.AppConfig)
        assert c.project_root != ""

    def test_get_tuning_works_via_config(self):
        import modules.config as cfg

        t = cfg.get_tuning()
        assert isinstance(t, cfg.TuningConfig)

