"""
向后兼容层 — 模块级常量和 OpenAI Client Proxy

本模块保留了旧代码中直接 import 的所有模块级常量（SOVITS_URL, MODEL_NAME, ...），
以及 OpenAI 延迟初始化代理。新代码应优先使用 AppConfig / TuningConfig。

迁移指南:
  旧: from modules.config import MODEL_NAME, SOVITS_URL
  新: cfg = load_config(); cfg.model_name, cfg.sovits_url
"""

from __future__ import annotations

import os
from typing import Optional

from .config_base import (
    GPT_SOVITS_ROOT,
    PROJECT_ROOT,
    _clean_env_value,
    _env_vars,
    get_yaml_config,
)

# ---- API 配置（延迟创建 OpenAI client） ----
_yaml_cfg = get_yaml_config()
_api_cfg = _yaml_cfg.get("api", {}) if isinstance(_yaml_cfg, dict) else {}
_audio_cfg = _yaml_cfg.get("audio", {}) if isinstance(_yaml_cfg, dict) else {}

_api_key = _clean_env_value(
    os.getenv("ARK_API_KEY")
    or _env_vars.get("ARK_API_KEY")
    or _api_cfg.get("ark_api_key")
)
_base_url = (
    _clean_env_value(
        os.getenv("ARK_BASE_URL")
        or _env_vars.get("ARK_BASE_URL")
        or _api_cfg.get("ark_base_url")
    )
    or "https://ark.cn-beijing.volces.com/api/v3"
)
_client = None  # 延迟初始化


def _get_client():
    """按需创建 OpenAI 客户端，避免导入时产生网络连接。"""
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url=_base_url,
            api_key=_api_key,
        )
    return _client


class _ClientProxy:
    """透明代理：首次属性访问时才创建真正的 OpenAI 客户端。"""

    def __getattr__(self, name):
        return getattr(_get_client(), name)


# 向后兼容：modules.config.client 可直接使用
client = _ClientProxy()


# ---- 音频/TTS 配置常量 ----
SOVITS_URL: str = (
    _clean_env_value(os.getenv("SOVITS_URL") or _api_cfg.get("sovits_url"))
    or "http://127.0.0.1:9880"
)
_ref_audio_path = str(_audio_cfg.get("ref_audio_path", "assets/audio_ref/大家好，我是虚拟歌手洛天依.wav"))
REF_AUDIO: str = _ref_audio_path if os.path.isabs(_ref_audio_path) else os.path.join(PROJECT_ROOT, _ref_audio_path)
PROMPT_TEXT: str = str(
    _audio_cfg.get("prompt_text", "大家好，我是虚拟歌手洛天依，欢迎来到我的十周年生日会直播。")
)

# ---- GPT-SoVITS 路径（使用内嵌路径）----
GPT_SOVITS_PATH: str = GPT_SOVITS_ROOT

# ---- 模型名称 ----
MODEL_NAME: Optional[str] = _clean_env_value(
    os.getenv("MODEL_NAME")
    or _env_vars.get("MODEL_NAME")
    or _api_cfg.get("model_name")
)

# ---- 嵌入模型名称（可选）----
EMBEDDING_MODEL_NAME: Optional[str] = _clean_env_value(
    os.getenv("EMBEDDING_MODEL_NAME")
    or _env_vars.get("EMBEDDING_MODEL_NAME")
    or _api_cfg.get("embedding_model_name")
)

# ---- System Prompt（支持文件或环境变量）----
_prompt_file = _clean_env_value(_env_vars.get("SYSTEM_PROMPT_FILE"))
if _prompt_file:
    _prompt_path = os.path.join(PROJECT_ROOT, _prompt_file)
    if os.path.exists(_prompt_path):
        with open(_prompt_path, encoding="utf-8") as _f:
            SYSTEM_PROMPT: str = _f.read()
    else:
        SYSTEM_PROMPT = _clean_env_value(_env_vars.get("SYSTEM_PROMPT")) or ""
else:
    SYSTEM_PROMPT = _clean_env_value(_env_vars.get("SYSTEM_PROMPT")) or ""

# ---- 电脑控制配置 ----
_controller_cfg = get_yaml_config().get("controller", {})
CONTROLLER_ENABLED: bool = _controller_cfg.get("enabled", False)
CONTROLLER_FAILSAFE: bool = _controller_cfg.get("failsafe", True)
CONTROLLER_APP_WHITELIST: dict = _controller_cfg.get("app_whitelist", {})

# ---- 听觉配置 ----
_ear_cfg = get_yaml_config().get("ear", {})
EAR_ENABLED: bool = _ear_cfg.get("enabled", True)
EAR_MODEL_SIZE: str = _ear_cfg.get("model_size", "base")
