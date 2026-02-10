"""
配置模块
"""
import os
import yaml
import dotenv
from openai import OpenAI

# 加载环境变量
dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# 加载 YAML 配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# --- 配置区 ---
env_vars = dotenv.dotenv_values(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

def _clean_env_value(value):
    if value is None:
        return None
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value

api_key = _clean_env_value(env_vars.get("ARK_API_KEY"))
client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=api_key,
)
SOVITS_URL = "http://127.0.0.1:9880"
REF_AUDIO = os.path.join(os.path.dirname(__file__), "..", "assets", "audio_ref", "大家好，我是虚拟歌手洛天依.wav")
PROMPT_TEXT = "大家好，我是虚拟歌手洛天依，欢迎来到我的十周年生日会直播。"

# ChromaDB 数据目录
data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
os.makedirs(data_dir, exist_ok=True)

# GPT-SoVITS 路径
GPT_SOVITS_PATH = _clean_env_value(env_vars.get("GPT_SOVITS_PATH"))

# model_name 
MODEL_NAME = _clean_env_value(env_vars.get("MODEL_NAME"))

# system prompt
SYSTEM_PROMPT = _clean_env_value(env_vars.get("SYSTEM_PROMPT"))

# 电脑控制配置
CONTROLLER_ENABLED = config.get('controller', {}).get('enabled', False)
CONTROLLER_FAILSAFE = config.get('controller', {}).get('failsafe', True)
CONTROLLER_APP_WHITELIST = config.get('controller', {}).get('app_whitelist', {})