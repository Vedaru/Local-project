# utils.py - 工具模块

import re
import jieba.posseg as pseg
import subprocess
import os
import time
import requests
from .logging_config import get_logger

logger = get_logger('utils')

PUNCTUATION = ['。', '！', '？', '!', '?', '\n', '；', ';', '：', ':', '，', ',']

def clean_text(text):
    """清除表情符号和多余特殊字符"""
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s' + "".join(PUNCTUATION) + r']', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_entities(text):
    """从文本中自动提取可能的实体"""
    entities = set()
    words = pseg.cut(text)
    
    for word, flag in words:
        if flag in ['nr', 'ns', 'nt', 'nz', 'n']:
            if len(word) >= 1:
                entities.add(word)
        
        if any(word.endswith(suffix) for suffix in ['公司', '大学', '医院', '学校', '银行', '政府', '中心', '局', '部']):
            entities.add(word)
        
        if re.match(r'\d{11}', word):
            entities.add(word)
        if '@' in word and '.' in word:
            entities.add(word)
    
    return entities

def start_gpt_sovits_api(gpt_sovits_path):
    """启动 GPT-SoVITS API 服务"""
    if not gpt_sovits_path or not os.path.exists(gpt_sovits_path):
        logger.error("GPT-SoVITS 路径未设置或不存在，请检查环境变量 GPT_SOVITS_PATH")
        return None
    
    api_script = os.path.join(gpt_sovits_path, 'api_v2.py')
    if not os.path.exists(api_script):
        logger.error(f"未找到 API 脚本: {api_script}")
        return None
    
    # 使用 runtime\python.exe
    python_exe = os.path.join(gpt_sovits_path, 'runtime', 'python.exe')
    if not os.path.exists(python_exe):
        logger.error(f"未找到 Python 可执行文件: {python_exe}")
        return None
    
    try:
        logger.info(f"正在启动 GPT-SoVITS API 服务，使用脚本: {api_script}，Python: {python_exe}")
        # 将输出保存到日志文件，并设置 UTF-8 编码以避免 Unicode 错误
        log_path = os.path.join(gpt_sovits_path, 'gpt_sovits.log')
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        with open(log_path, 'w', encoding='utf-8') as logfile:
            process = subprocess.Popen([python_exe, api_script], cwd=gpt_sovits_path, stdout=logfile, stderr=logfile, env=env)
        
        # 等待服务启动
        logger.info("等待 GPT-SoVITS API 服务启动...")
        for _ in range(60):  # 增加到60秒
            time.sleep(1)
            if check_sovits_service():
                logger.info("GPT-SoVITS API 服务已成功启动并可用。")
                return process
        
        logger.warning("GPT-SoVITS API 服务启动超时，可能未成功启动。")
        process.terminate()
        return None
    except Exception as e:
        logger.error(f"启动 GPT-SoVITS API 服务失败: {e}", exc_info=True)
def filter_emotion_tags(text):
    """过滤掉表情标签，避免在语音中读出"""
    # 移除所有 [表情] 标签
    text = re.sub(r'\[开心\]|\[生气\]|\[委屈\]|\[疑惑\]|\[嘲笑\]|\[宕机\]', '', text)
    return text.strip()

def check_sovits_service(url="http://127.0.0.1:9880/docs"):
    """检查 GPT-SoVITS 服务是否可用"""
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except:
        return False