# utils.py - 工具模块

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional, Union

import jieba.posseg as pseg
import requests

from .logging_config import get_logger

logger = get_logger("utils")

PUNCTUATION = ["。", "！", "？", "!", "?", "\n", "；", ";", "：", ":", "，", ","]

# 预编译 Avatar 控制标签正则，避免每次调用都重新编译
_EMOTION_TAG_RE = re.compile(r"(?:\[|【)\s*(开心|生气|委屈|疑惑|嘲笑|宕机)\s*(?:\]|】)")
_MOTION_TAG_RE = re.compile(
    r"(?:\[|【)\s*(?:动作|motion)\s*[:：]\s*([^\]】:：\s]+)(?:\s*[:：]\s*(-?\d+))?\s*(?:\]|】)",
    re.IGNORECASE,
)
_BRACKETED_SEGMENT_RE = re.compile(r"(\[[^\[\]]{1,24}\]|【[^【】]{1,24}】|\([^()]{1,24}\)|（[^（）]{1,24}）)")
_EMOTION_MARKER_PREFIXES = ("表情:", "表情：", "emotion:", "emotion：")

# 仅用于清理口语化情绪旁白，不影响正常括号内容
_EMOTION_MARKER_KEYWORDS = (
    "开心",
    "高兴",
    "生气",
    "愤怒",
    "委屈",
    "难过",
    "伤心",
    "疑惑",
    "困惑",
    "嘲笑",
    "宕机",
    "微笑",
    "笑",
    "大笑",
    "苦笑",
    "尴尬",
    "叹气",
    "思考",
    "沉思",
    "害羞",
    "惊讶",
    "兴奋",
    "认真",
    "平静",
    "smile",
    "laugh",
    "sigh",
    "thinking",
    "happy",
    "sad",
    "angry",
    "surprised",
    "confused",
    "表情包",
    "emoji",
    "emote",
    "颜文字",
    "颜表情",
)


def clean_text(text: str) -> str:
    """清除表情符号和多余特殊字符"""
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s" + "".join(PUNCTUATION) + r"]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_entities(text: str) -> set[str]:
    """从文本中自动提取可能的实体"""
    entities = set()
    words = pseg.cut(text)

    for word, flag in words:
        if flag in ["nr", "ns", "nt", "nz", "n"] and len(word) >= 1:
            entities.add(word)

        if any(
            word.endswith(suffix) for suffix in ["公司", "大学", "医院", "学校", "银行", "政府", "中心", "局", "部"]
        ):
            entities.add(word)

        if re.match(r"\d{11}", word):
            entities.add(word)
        if "@" in word and "." in word:
            entities.add(word)

    return entities


def start_gpt_sovits_api(gpt_sovits_path: Optional[str]):
    """启动 GPT-SoVITS API 服务"""
    if not gpt_sovits_path or not os.path.exists(gpt_sovits_path):
        logger.error("GPT-SoVITS 路径未设置或不存在，请检查 modules/gpt_sovits 目录")
        return None

    api_script = os.path.join(gpt_sovits_path, "api_v2.py")
    if not os.path.exists(api_script):
        logger.error(f"未找到 API 脚本: {api_script}")
        return None

    # 使用项目根目录下的 runtime\python.exe
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = os.path.join(project_root, "runtime", "python.exe")
    if not os.path.exists(python_exe):
        fallback_python = shutil.which("python")
        if not fallback_python:
            logger.error(f"未找到 Python 可执行文件: {python_exe}，且 PATH 中没有 python")
            return None
        logger.warning(
            "未找到 runtime\\python.exe，回退使用 PATH Python: %s",
            fallback_python,
        )
        python_exe = fallback_python

    try:
        logger.info(f"正在启动 GPT-SoVITS API 服务，使用脚本: {api_script}，Python: {python_exe}")
        # 将输出保存到日志文件，并设置 UTF-8 编码以避免 Unicode 错误
        log_path = os.path.join(gpt_sovits_path, "gpt_sovits.log")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # 避免 pydantic 在扫描环境插件时因损坏的 dist-info 元数据导致启动失败。
        env.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")
        with open(log_path, "w", encoding="utf-8") as logfile:
            popen_kwargs: dict[str, Any] = {
                "cwd": gpt_sovits_path,
                "stdout": logfile,
                "stderr": logfile,
                "env": env,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            process = subprocess.Popen([python_exe, api_script], **popen_kwargs)

        # 等待服务启动
        logger.info("等待 GPT-SoVITS API 服务启动...")
        for _ in range(60):  # 增加到60秒
            time.sleep(1)
            if process.poll() is not None:
                logger.error(
                    "GPT-SoVITS API 进程在启动阶段提前退出，退出码=%s。请检查日志: %s",
                    process.returncode,
                    log_path,
                )
                return None
            if check_sovits_service():
                logger.info("GPT-SoVITS API 服务已成功启动并可用。")
                return process

        logger.warning(f"GPT-SoVITS API 服务启动超时，可能未成功启动。请检查日志: {log_path}")
        process.terminate()
        return None
    except Exception as e:
        logger.error(f"启动 GPT-SoVITS API 服务失败: {e}", exc_info=True)
        return None


def filter_emotion_tags(text: str) -> str:
    """过滤掉 Avatar 控制标签和情绪旁白，避免在语音中读出。"""
    return sanitize_dialogue_text(text)


def extract_emotion_tags(text: str) -> list[str]:
    """提取文本中的情绪标签（按出现顺序）。"""
    if not text:
        return []
    return _EMOTION_TAG_RE.findall(text)


def extract_motion_commands(text: str) -> list[tuple[str, Optional[int]]]:
    """提取文本中的动作标签，格式支持 [动作:Group] 或 [动作:Group:Index]。"""
    if not text:
        return []

    commands: list[tuple[str, Optional[int]]] = []
    for m in _MOTION_TAG_RE.finditer(text):
        group = m.group(1).strip()
        index_raw = m.group(2)
        index = int(index_raw) if index_raw is not None else None
        if group:
            commands.append((group, index))

    return commands


def strip_avatar_control_tags(text: str) -> str:
    """移除情绪/动作控制标签，保留其余文本。"""
    if not text:
        return ""

    cleaned = _EMOTION_TAG_RE.sub("", text)
    cleaned = _MOTION_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def _looks_like_emotion_marker(segment: str) -> bool:
    """判断括号片段是否为情绪/舞台提示。"""
    if not segment:
        return False

    stripped = segment.strip()
    if _EMOTION_TAG_RE.fullmatch(stripped) or _MOTION_TAG_RE.fullmatch(stripped):
        return True

    if len(stripped) < 2:
        return False

    inner = stripped[1:-1].strip().lower()
    if not inner:
        return False

    normalized = re.sub(r"\s+", "", inner)
    if normalized.startswith(("动作:", "动作：", "motion:", "motion：")):
        return True

    # 仅把带前缀的元信息视作情绪标记，避免误删“表情包”等普通文本。
    if normalized.startswith(_EMOTION_MARKER_PREFIXES):
        return True

    if len(normalized) > 16:
        return False

    return any(keyword in normalized for keyword in _EMOTION_MARKER_KEYWORDS)


def sanitize_dialogue_text(text: str) -> str:
    """清理控制标签与情绪舞台提示，让回复更自然。"""
    if not text:
        return ""

    cleaned = strip_avatar_control_tags(text)

    def _replace(match: re.Match[str]) -> str:
        segment = match.group(0)
        return "" if _looks_like_emotion_marker(segment) else segment

    cleaned = _BRACKETED_SEGMENT_RE.sub(_replace, cleaned)
    cleaned = re.sub(r"(?:表情包|颜文字|颜表情|\bemoji\b|\bemote\b)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\]|【\s*】|\(\s*\)|（\s*）", "", cleaned)
    cleaned = re.sub(r"[\[\]【】()（）]", "", cleaned)
    cleaned = re.sub(r"\s+([，。！？!?；;：:,])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """将文本截断到指定长度（长度包含 suffix）。"""
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    if len(suffix) >= max_length:
        return suffix[:max_length]
    return text[: max_length - len(suffix)] + suffix


def normalize_whitespace(text: Optional[str]) -> str:
    """合并连续空白字符并去除首尾空白。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def safe_json_loads(data: Union[str, bytes], default: Any = None) -> Any:
    """安全解析 JSON，失败时返回 default。"""
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def clamp_value(value: float, min_val: float, max_val: float) -> float:
    """将数值限制在闭区间 [min_val, max_val] 内。"""
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    return max(min_val, min(max_val, value))


def is_valid_identifier(name: str) -> bool:
    """检查名称是否仅包含字母、数字、下划线和短横线。"""
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]+", name or ""))


def check_sovits_service(url: str = "http://127.0.0.1:9880/docs") -> bool:
    """检查 GPT-SoVITS 服务是否可用"""
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except Exception:
        return False
