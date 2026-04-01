"""
配置模块 — 集中管理所有配置项

提供两种访问方式:
1. AppConfig 数据类 + load_config() — 推荐的新接口
2. 模块级常量 (SOVITS_URL, MODEL_NAME, …) — 向后兼容

优化点：
- 消除 dotenv 重复加载（原先 load_dotenv + dotenv_values 各调一次）
- 路径常量统一通过 PROJECT_ROOT 派生
- OpenAI 客户端延迟创建，避免导入时副作用
- 新增 AppConfig 数据类，集中管理所有应用配置
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import dotenv
import yaml

# ---- 路径常量 ----
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

# ---- GPT-SoVITS 内嵌路径（固定相对路径）----
GPT_SOVITS_ROOT = os.path.join(os.path.dirname(__file__), "gpt_sovits")

# ---- 统一加载 .env（只调一次）----
_env_vars = dotenv.dotenv_values(dotenv_path=_ENV_PATH)
# 也设置到 os.environ 以兼容第三方库（如 openai SDK 的自动检测）
dotenv.load_dotenv(dotenv_path=_ENV_PATH)

# ---- 加载 YAML 配置 ----
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    config = yaml.safe_load(_f)


def _clean_env_value(value):
    """去除环境变量值两端的空白和多余引号"""
    if value is None:
        return None
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def _to_int(value, default: int) -> int:
    """安全转换为 int，失败时回退默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    """安全转换为 float，失败时回退默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ===================== AppConfig 数据类 =====================


@dataclass
class AppConfig:
    """集中管理所有应用配置的数据类"""

    # ---- 路径 ----
    project_root: str = PROJECT_ROOT

    # ---- API / LLM ----
    ark_api_key: Optional[str] = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model_name: Optional[str] = None
    embedding_model_name: Optional[str] = None

    # ---- TTS / 语音 ----
    sovits_url: str = "http://127.0.0.1:9880"
    ref_audio: str = ""
    prompt_text: str = ""
    gpt_sovits_path: Optional[str] = None
    audio_sample_rate: int = 32000

    # ---- System Prompt ----
    system_prompt: Optional[str] = None

    # ---- 记忆系统 ----
    memory_data_dir: str = ""
    memory_collection_name: str = "seeka_memory"

    # ---- 日志 ----
    log_dir: str = ""

    # ---- 电脑控制 ----
    controller_enabled: bool = False
    controller_failsafe: bool = True
    controller_app_whitelist: dict[str, str] = field(default_factory=dict)

    # ---- Avatar ----
    avatar_width: int = 400
    avatar_height: int = 600
    avatar_x: int = 100
    avatar_y: int = 100

    # ---- Agent ----
    agent_max_steps: int = 100
    agent_task_timeout_seconds: float = 300.0

    # ---- 听觉模块 ----
    ear_enabled: bool = True
    ear_model_size: str = "base"


def load_config(config_path: Optional[str] = None, env_path: Optional[str] = None) -> AppConfig:
    """从 config.yaml 和 .env 加载配置, 返回 AppConfig 实例。

    Args:
        config_path: YAML 配置文件路径（默认为项目根目录的 config.yaml）
        env_path: .env 文件路径（默认为项目根目录的 .env）

    Returns:
        填充好的 AppConfig 实例
    """
    cfg_path = config_path or _CONFIG_PATH
    e_path = env_path or _ENV_PATH

    # 加载 .env
    env = dotenv.dotenv_values(dotenv_path=e_path)

    # 加载 YAML
    yaml_cfg: dict = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            yaml_cfg = yaml.safe_load(f) or {}

    # 解析 system prompt (文件或环境变量)
    system_prompt = None
    prompt_file = _clean_env_value(env.get("SYSTEM_PROMPT_FILE"))
    if prompt_file:
        prompt_path = os.path.join(PROJECT_ROOT, prompt_file)
        if os.path.exists(prompt_path):
            with open(prompt_path, encoding="utf-8") as f:
                system_prompt = f.read()
        else:
            system_prompt = _clean_env_value(env.get("SYSTEM_PROMPT"))
    else:
        system_prompt = _clean_env_value(env.get("SYSTEM_PROMPT"))

    # 音频配置
    audio_cfg = yaml_cfg.get("audio", {})
    memory_cfg = yaml_cfg.get("memory", {})
    logging_cfg = yaml_cfg.get("logging", {})
    controller_cfg = yaml_cfg.get("controller", {})
    ear_cfg = yaml_cfg.get("ear", {})
    agent_cfg = yaml_cfg.get("agent", {})

    return AppConfig(
        project_root=PROJECT_ROOT,
        # API
        ark_api_key=_clean_env_value(env.get("ARK_API_KEY")),
        ark_base_url=os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        model_name=_clean_env_value(env.get("MODEL_NAME")),
        embedding_model_name=_clean_env_value(env.get("EMBEDDING_MODEL_NAME")),
        # TTS
        sovits_url=yaml_cfg.get("api", {}).get("sovits_url", "http://127.0.0.1:9880"),
        ref_audio=os.path.join(
            PROJECT_ROOT,
            audio_cfg.get("ref_audio_path", "assets/audio_ref/大家好，我是虚拟歌手洛天依.wav"),
        ),
        prompt_text=audio_cfg.get("prompt_text", "大家好，我是虚拟歌手洛天依，欢迎来到我的十周年生日会直播。"),
        gpt_sovits_path=GPT_SOVITS_ROOT,
        audio_sample_rate=audio_cfg.get("sample_rate", 32000),
        # System Prompt
        system_prompt=system_prompt,
        # 记忆
        memory_data_dir=os.path.join(PROJECT_ROOT, memory_cfg.get("data_dir", "data/memoripy")),
        memory_collection_name=memory_cfg.get("collection_name", "seeka_memory"),
        # 日志
        log_dir=os.path.join(PROJECT_ROOT, logging_cfg.get("log_dir", "data/logs")),
        # 电脑控制
        controller_enabled=controller_cfg.get("enabled", False),
        controller_failsafe=controller_cfg.get("failsafe", True),
        controller_app_whitelist=controller_cfg.get("app_whitelist", {}),
        # Agent
        agent_max_steps=_to_int(agent_cfg.get("max_steps", 100), 100),
        agent_task_timeout_seconds=_to_float(agent_cfg.get("task_timeout_seconds", 300), 300.0),
        # 听觉
        ear_enabled=ear_cfg.get("enabled", True),
        ear_model_size=ear_cfg.get("model_size", "base"),
    )


# ===================== 向后兼容的模块级常量 =====================


# ---- API 配置（延迟创建 OpenAI client）----
_api_key = _clean_env_value(_env_vars.get("ARK_API_KEY"))
_client = None  # 延迟初始化


def _get_client():
    """按需创建 OpenAI 客户端，避免导入时产生网络连接"""
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=_api_key,
        )
    return _client


# 为向后兼容保留 ``client`` 属性，但实际改为 property-like 访问
# 由于模块级别无法用 property，这里使用一个透明代理类
class _ClientProxy:
    """透明代理：首次属性访问时才创建真正的 OpenAI 客户端"""

    def __getattr__(self, name):
        return getattr(_get_client(), name)


client = _ClientProxy()


# ---- 音频/TTS 配置 ----
SOVITS_URL = "http://127.0.0.1:9880"
REF_AUDIO = os.path.join(PROJECT_ROOT, "assets", "audio_ref", "大家好，我是虚拟歌手洛天依.wav")
PROMPT_TEXT = "大家好，我是虚拟歌手洛天依，欢迎来到我的十周年生日会直播。"

# ---- GPT-SoVITS 路径（使用内嵌路径）----
GPT_SOVITS_PATH = GPT_SOVITS_ROOT

# ---- 模型名称 ----
MODEL_NAME = _clean_env_value(_env_vars.get("MODEL_NAME"))

# ---- 嵌入模型名称（可选，用于 memoripy 记忆系统）----
# 设置为 Volcengine 嵌入模型端点 ID 或模型名称（如 doubao-embedding）
# 如果未设置，将回退到本地 sentence-transformers
EMBEDDING_MODEL_NAME = _clean_env_value(_env_vars.get("EMBEDDING_MODEL_NAME"))

# ---- System Prompt（支持文件或环境变量）----
_prompt_file = _clean_env_value(_env_vars.get("SYSTEM_PROMPT_FILE"))
if _prompt_file:
    _prompt_path = os.path.join(PROJECT_ROOT, _prompt_file)
    if os.path.exists(_prompt_path):
        with open(_prompt_path, encoding="utf-8") as _f:
            SYSTEM_PROMPT = _f.read()
    else:
        # 回退：尝试从环境变量读取（兼容旧配置）
        SYSTEM_PROMPT = _clean_env_value(_env_vars.get("SYSTEM_PROMPT"))
else:
    SYSTEM_PROMPT = _clean_env_value(_env_vars.get("SYSTEM_PROMPT"))

# ---- 电脑控制配置 ----
_controller_cfg = config.get("controller", {})
CONTROLLER_ENABLED = _controller_cfg.get("enabled", False)
CONTROLLER_FAILSAFE = _controller_cfg.get("failsafe", True)
CONTROLLER_APP_WHITELIST = _controller_cfg.get("app_whitelist", {})

# ---- 听觉配置 ----
_ear_cfg = config.get("ear", {})
EAR_ENABLED = _ear_cfg.get("enabled", True)
EAR_MODEL_SIZE = _ear_cfg.get("model_size", "base")
