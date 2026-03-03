"""
配置模块 — 集中管理所有配置项

优化点：
- 消除 dotenv 重复加载（原先 load_dotenv + dotenv_values 各调一次）
- 路径常量统一通过 PROJECT_ROOT 派生
- OpenAI 客户端延迟创建，避免导入时副作用
"""

import os

import dotenv
import yaml

# ---- 路径常量 ----
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

# ---- 统一加载 .env（只调一次）----
_env_vars = dotenv.dotenv_values(dotenv_path=_ENV_PATH)
# 也设置到 os.environ 以兼容第三方库（如 openai SDK 的自动检测）
dotenv.load_dotenv(dotenv_path=_ENV_PATH)

# ---- 加载 YAML 配置 ----
with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
    config = yaml.safe_load(_f)


def _clean_env_value(value):
    """去除环境变量值两端的空白和多余引号"""
    if value is None:
        return None
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


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

# ---- ChromaDB 数据目录 ----
data_dir = os.path.join(PROJECT_ROOT, "data", "chroma_db")
os.makedirs(data_dir, exist_ok=True)

# ---- GPT-SoVITS 路径 ----
GPT_SOVITS_PATH = _clean_env_value(_env_vars.get("GPT_SOVITS_PATH"))

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
        with open(_prompt_path, "r", encoding="utf-8") as _f:
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
