"""
配置模块 — 统一入口（向后兼容薄层）

本文件作为统一的 ``from modules.config import ...`` 入口，
内部委托给三个子模块:
  - config_base.py:   路径常量、环境加载、辅助函数
  - config_app.py:    AppConfig + load_config()
  - config_tuning.py: TuningConfig + load_tuning() + get_tuning()
  - config_legacy.py:  向后兼容的模块级常量、OpenAI client proxy

新代码推荐直接导入子模块:
  from modules.config_app import AppConfig, load_config
  from modules.config_tuning import TuningConfig, load_tuning, get_tuning
"""

# ---- 基础层: 路径 / 辅助函数 ----
# ---- 应用配置 ----
from .config_app import AppConfig, load_config, sanitize_for_logging  # noqa: F401
from .config_base import (  # noqa: F401
    CONFIG_PATH,
    ENV_PATH,
    GPT_SOVITS_ROOT,
    PROJECT_ROOT,
    TUNING_PATH,
    EnvironmentAwareConfig,
    _clean_env_value,
    _env_int,
    _env_str,
    _read_bool,
    _to_float,
    _to_int,
    get_cached_config,
    get_env_vars,
    get_yaml_config,
    invalidate_config_cache,
)

# ---- 向后兼容常量 & OpenAI client ----
from .config_legacy import (  # noqa: F401
    CONTROLLER_APP_WHITELIST,
    CONTROLLER_ENABLED,
    CONTROLLER_FAILSAFE,
    EAR_ENABLED,
    EAR_MODEL_SIZE,
    EMBEDDING_MODEL_NAME,
    GPT_SOVITS_PATH,
    MODEL_NAME,
    PROMPT_TEXT,
    REF_AUDIO,
    SOVITS_URL,
    SYSTEM_PROMPT,
    client,
)

# ---- 行为调优配置 ----
from .config_tuning import (  # noqa: F401
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

__all__ = [
    # base
    "PROJECT_ROOT",
    "CONFIG_PATH",
    "ENV_PATH",
    "TUNING_PATH",
    "GPT_SOVITS_ROOT",
    "EnvironmentAwareConfig",
    "_clean_env_value",
    "_to_int",
    "_to_float",
    "_read_bool",
    "_env_str",
    "_env_int",
    "get_yaml_config",
    "get_env_vars",
    # app
    "AppConfig",
    "sanitize_for_logging",
    "get_cached_config",
    "invalidate_config_cache",
    "load_config",
    # tuning
    "TuningConfig",
    "load_tuning",
    "get_tuning",
    "ServicesTuning",
    "OrchestratorTuning",
    "VoiceTuning",
    "ExpressionTuning",
    "GatewayTuning",
    "ClientTuning",
    # legacy
    "client",
    "SOVITS_URL",
    "REF_AUDIO",
    "PROMPT_TEXT",
    "GPT_SOVITS_PATH",
    "MODEL_NAME",
    "EMBEDDING_MODEL_NAME",
    "SYSTEM_PROMPT",
    "CONTROLLER_ENABLED",
    "CONTROLLER_FAILSAFE",
    "CONTROLLER_APP_WHITELIST",
    "EAR_ENABLED",
    "EAR_MODEL_SIZE",
]
