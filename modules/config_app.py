"""
应用配置层 — AppConfig 数据类 + load_config() 工厂函数

管理运行时配置项：
- API Key / LLM 模型名
- TTS (GPT-SoVITS) 路径与参数
- Avatar 尺寸/位置
- System Prompt
- Agent / Ear / Controller 开关
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import dotenv
import yaml

from .config_base import (
    CONFIG_PATH,
    ENV_PATH,
    GPT_SOVITS_ROOT,
    PROJECT_ROOT,
    _clean_env_value,
    _to_float,
    _to_int,
    get_yaml_config,
)


@dataclass
class AppConfig:
    """集中管理所有应用配置的数据类。"""

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
    cfg_path = config_path or CONFIG_PATH
    e_path = env_path or ENV_PATH

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

    # 各子配置段
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
