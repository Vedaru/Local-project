# utils.py - 工具模块

import atexit
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional, Tuple, Union

import jieba.posseg as pseg
import requests

from .logging_config import get_logger

logger = get_logger("utils")

# 本地回环地址：健康检查 / SoVITS / 微服务互访应绕过系统代理（梯子）
_LOCAL_HOST_MARKERS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")
_DEFAULT_NO_PROXY = "127.0.0.1,localhost,::1"
_local_requests_session: Optional[requests.Session] = None


def ensure_local_no_proxy_env() -> None:
    """合并 NO_PROXY，避免 HTTP_PROXY 把本机服务请求拐到梯子上。"""
    for key in ("NO_PROXY", "no_proxy"):
        current = (os.environ.get(key) or "").strip()
        parts = [p.strip() for p in current.split(",") if p.strip()]
        for marker in _LOCAL_HOST_MARKERS:
            if marker not in parts:
                parts.append(marker)
        os.environ[key] = ",".join(parts) if parts else _DEFAULT_NO_PROXY


def is_local_service_url(url: str) -> bool:
    lowered = (url or "").strip().lower()
    return any(marker in lowered for marker in _LOCAL_HOST_MARKERS)


def _get_local_requests_session() -> requests.Session:
    global _local_requests_session
    if _local_requests_session is None:
        ensure_local_no_proxy_env()
        session = requests.Session()
        session.trust_env = False
        _local_requests_session = session
    return _local_requests_session


def requests_get_local(url: str, **kwargs: Any) -> requests.Response:
    """GET 本地 HTTP 服务，忽略系统/环境变量代理。"""
    kwargs.setdefault("timeout", 5)
    return _get_local_requests_session().get(url, **kwargs)


def requests_post_local(url: str, **kwargs: Any) -> requests.Response:
    """POST 本地 HTTP 服务，忽略系统/环境变量代理。"""
    kwargs.setdefault("timeout", 5)
    return _get_local_requests_session().post(url, **kwargs)


def http_get_json_local(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """urllib 版本地 GET + JSON 解析（供 monitor 等轻量调用方使用）。"""
    import urllib.request

    ensure_local_no_proxy_env()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url=url, method="GET")
    with opener.open(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        if isinstance(data, dict):
            return dict(data)
        return {"data": data}


def kill_process_tree(process: subprocess.Popen) -> None:
    """终止进程及其所有子进程（Windows 使用 taskkill /T，Unix 使用进程组信号）。"""
    if process is None:
        return
    try:
        if process.poll() is not None:
            return  # 已经退出
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        else:
            import signal

            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


# 进程树清理注册表：退出时自动终止所有注册的子进程
_subprocess_cleanup_registry: list[subprocess.Popen] = []


def register_subprocess_for_cleanup(process: subprocess.Popen) -> None:
    """注册子进程，确保主进程退出时自动终止。"""
    _subprocess_cleanup_registry.append(process)


def _cleanup_registered_subprocesses() -> None:
    """atexit 回调：终止所有注册的子进程。"""
    for proc in reversed(_subprocess_cleanup_registry):
        kill_process_tree(proc)
    _subprocess_cleanup_registry.clear()


atexit.register(_cleanup_registered_subprocesses)


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

        if any(word.endswith(suffix) for suffix in ["公司", "大学", "医院", "学校", "银行", "政府", "中心", "局", "部"]):
            entities.add(word)

        if re.match(r"\d{11}", word):
            entities.add(word)
        if "@" in word and "." in word:
            entities.add(word)

    return entities


def probe_sovits_tts_ready(
    base_url: str,
    *,
    ref_audio_path: str,
    prompt_text: str,
    probe_text: str = "测",
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 3.0,
) -> bool:
    """
    等待 POST /tts 真正可用（不仅是 /docs 可访问）。

    首次推理可能较慢；502/503 通常表示模型仍在加载或并发过载。
    """
    if not ref_audio_path or not os.path.exists(ref_audio_path):
        logger.warning("SoVITS TTS 探针跳过：参考音频不存在 (%s)", ref_audio_path)
        return False

    url = f"{base_url.rstrip('/')}/tts"
    payload = {
        "text": probe_text,
        "text_lang": "zh",
        "ref_audio_path": ref_audio_path,
        "prompt_lang": "zh",
        "prompt_text": prompt_text or "",
        "text_split_method": "cut1",
        "media_type": "raw",
        "streaming_mode": 0,
        "parallel_infer": False,
    }
    deadline = time.monotonic() + max(5.0, float(timeout_sec))
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            response = requests_post_local(
                url,
                json=payload,
                timeout=(5, min(90.0, max(10.0, timeout_sec))),
            )
            if response.status_code == 200 and response.content:
                logger.info(
                    "SoVITS TTS 探针成功 (attempt=%s, bytes=%s)",
                    attempt,
                    len(response.content),
                )
                return True
            if response.status_code in {502, 503, 504}:
                logger.debug(
                    "SoVITS TTS 探针尚未就绪 status=%s attempt=%s",
                    response.status_code,
                    attempt,
                )
            elif response.status_code == 400:
                body = (response.text or "")[:400]
                logger.warning("SoVITS TTS 探针参数/推理错误 status=400 body=%s", body)
                return False
            else:
                body = (response.text or "")[:300]
                logger.warning(
                    "SoVITS TTS 探针失败 status=%s body=%s",
                    response.status_code,
                    body,
                )
        except Exception as exc:
            logger.debug("SoVITS TTS 探针异常 attempt=%s: %s", attempt, exc)
        time.sleep(max(0.5, float(poll_interval_sec)))

    logger.warning("SoVITS TTS 探针超时 (%.0fs)", timeout_sec)
    return False


def start_gpt_sovits_api(
    gpt_sovits_path: Optional[str],
    *,
    sovits_base_url: str = "http://127.0.0.1:9880",
    ref_audio_path: str = "",
    prompt_text: str = "",
    probe_tts_ready: bool = True,
) -> Tuple[Optional[subprocess.Popen], bool]:
    """启动 GPT-SoVITS API 服务。返回 (进程, TTS 是否已通过探针就绪)。"""
    if not gpt_sovits_path or not os.path.exists(gpt_sovits_path):
        logger.error("GPT-SoVITS 路径未设置或不存在，请检查 modules/gpt_sovits 目录")
        return None, False

    api_script = os.path.join(gpt_sovits_path, "api_v2.py")
    if not os.path.exists(api_script):
        logger.error(f"未找到 API 脚本: {api_script}")
        return None, False

    # 使用项目根目录下的 runtime\python.exe
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = os.path.join(project_root, "runtime", "python.exe")
    if not os.path.exists(python_exe):
        logger.error(
            "未找到 runtime\\python.exe，请先运行 scripts\\setup_runtime.bat 安装项目 Runtime"
        )
        return None, False

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

        # 注册子进程，确保主进程退出时自动终止
        register_subprocess_for_cleanup(process)

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
                return None, False
            if check_sovits_service():
                logger.info("GPT-SoVITS API 服务已成功启动并可用。")
                tts_ready = False
                if probe_tts_ready and ref_audio_path:
                    logger.info("等待 SoVITS TTS 推理就绪（首次探针可能较慢）...")
                    tts_ready = probe_sovits_tts_ready(
                        sovits_base_url,
                        ref_audio_path=ref_audio_path,
                        prompt_text=prompt_text,
                    )
                else:
                    tts_ready = True
                return process, tts_ready

        logger.warning(f"GPT-SoVITS API 服务启动超时，可能未成功启动。请检查日志: {log_path}")
        kill_process_tree(process)
        return None, False
    except Exception as e:
        logger.error(f"启动 GPT-SoVITS API 服务失败: {e}", exc_info=True)
        return None, False


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
    """检查 GPT-SoVITS 服务是否可用（本地地址不走代理）。"""
    try:
        if is_local_service_url(url):
            response = requests_get_local(url, timeout=5)
        else:
            response = requests.get(url, timeout=5)
        return response.status_code == 200
    except Exception:
        return False
