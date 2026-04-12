"""
配置基础层 — 路径常量、环境变量加载、辅助函数

本模块提供:
- PROJECT_ROOT 等路径常量（所有子模块的根基）
- .env / config.yaml 的统一加载
- 类型安全的辅助函数: _clean_env_value, _to_int, _to_float, _read_bool, _env_str, _env_int

被 config_app.py 和 config_tuning.py 共同依赖，不应直接被业务代码 import。
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any, Optional

import dotenv
import yaml

if TYPE_CHECKING:
    from .config_app import AppConfig


# ---- 路径常量（全局唯一真相来源） ----
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
_DEFAULT_DEV_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
_DEFAULT_PROD_CONFIG_PATH = "/etc/local-project/config.yaml"
_TUNING_PATH = os.path.join(PROJECT_ROOT, "tuning.yaml")
GPT_SOVITS_ROOT = os.path.join(os.path.dirname(__file__), "gpt_sovits")


class EnvironmentAwareConfig:
    """根据运行环境解析配置文件路径。"""

    def __init__(self) -> None:
        self.environment = (os.getenv("APP_ENV") or "development").strip().lower()

    def get_config_path(self) -> str:
        explicit_path = (os.getenv("APP_CONFIG_PATH") or "").strip()
        if explicit_path:
            return explicit_path
        if self.environment == "production":
            return _DEFAULT_PROD_CONFIG_PATH
        return _DEFAULT_DEV_CONFIG_PATH


# ---- 模块级单例：配置路径和已加载的值 ----
CONFIG_PATH: str = EnvironmentAwareConfig().get_config_path()
# 向后兼容: 暴露 ENV_PATH / TUNING_PATH（config_app.py / config_tuning.py 使用）
ENV_PATH: str = _ENV_PATH
TUNING_PATH: str = _TUNING_PATH

# 统一加载 .env（只调一次）
_env_vars: dict[str, Optional[str]] = dotenv.dotenv_values(dotenv_path=_ENV_PATH)
# 也设置到 os.environ 以兼容第三方库（如 openai SDK 的自动检测）
dotenv.load_dotenv(dotenv_path=_ENV_PATH)

# 加载 YAML 配置
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, encoding="utf-8") as _f:
        _yaml_config: dict = yaml.safe_load(_f) or {}
else:
    _yaml_config = {}


def get_yaml_config() -> dict:
    """返回已加载的 YAML 配置字典（浅拷贝）。"""
    return dict(_yaml_config)


def get_env_vars() -> dict[str, Optional[str]]:
    """返回已加载的 .env 变量字典。"""
    return dict(_env_vars)


# ---- 配置缓存（线程安全，避免重复 load_config） ----
_config_cache_lock = threading.Lock()
_config_cache: AppConfig | None = None


def get_cached_config() -> AppConfig:
    """返回缓存的 AppConfig；首次调用时懒加载。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    with _config_cache_lock:
        if _config_cache is not None:
            return _config_cache
        from .config_app import load_config

        _config_cache = load_config()
        return _config_cache


def invalidate_config_cache() -> None:
    """清空配置缓存，用于测试或热重载场景。"""
    global _config_cache
    with _config_cache_lock:
        _config_cache = None


# ===================== 辅助函数 =====================


def _clean_env_value(value: object) -> Optional[str]:
    """去除环境变量值两端的空白和多余引号。"""
    if value is None:
        return None
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def _to_int(value: Any, default: int) -> int:
    """安全转换为 int，失败时回退默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    """安全转换为 float，失败时回退默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_bool(raw_value: object, default: bool = False) -> bool:
    """读取布尔环境变量或 YAML 值。"""
    if raw_value is None or str(raw_value).strip() == "":
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on", "True"}


def _env_str(env_name: str, fallback: Any, *, allow_empty: bool = False) -> str:
    """安全读取环境变量：os.getenv 优先，fallback 兜底。处理 os.getenv 返回的 "None" 字符串。

    Returns:
        环境变量的字符串值（非空时），或 fallback 的字符串表示。
    """
    raw = os.getenv(env_name)
    if raw is not None and raw.strip() != "" and raw.strip() != "None":
        return raw.strip()
    # fallback 可能是任意类型，安全转字符串
    if fallback is None:
        return "" if allow_empty else "0"
    s = str(fallback).strip()
    if not allow_empty and (s.lower() == "none" or s == ""):
        return "0"
    return s


def _env_int(env_name: str, fallback: int | None = None, *, minimum: int | None = None) -> int:
    """安全从环境变量或 fallback 读取整数。"""
    raw = _env_str(env_name, fallback)
    if not raw:
        raw = "0"
    val: int | None
    try:
        val = int(raw)
    except (ValueError, TypeError):
        val = fallback
    # 兜底：fallback 为 None 时使用默认值
    if val is None:
        return minimum if minimum is not None else 0
    if minimum is not None:
        return max(minimum, val)
    return val
