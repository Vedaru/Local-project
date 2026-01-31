"""
配置模块
"""
import os
import dotenv
from openai import OpenAI

# 加载环境变量
dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# --- 配置区 ---
env_vars = dotenv.dotenv_values(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
api_key = env_vars.get("ARK_API_KEY")
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
GPT_SOVITS_PATH = env_vars.get("GPT_SOVITS_PATH")

# model_name 
MODEL_NAME = env_vars.get("MODEL_NAME")

# system prompt
SYSTEM_PROMPT = env_vars.get("SYSTEM_PROMPT")