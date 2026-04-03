# voice.py - 语音模块（低延迟版）

import os
import queue
import subprocess
import threading
import unicodedata
import wave
from collections import deque
from typing import Optional, Union

import requests
from requests.adapters import HTTPAdapter

try:
    import pyaudio

    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False

from .config import GPT_SOVITS_PATH
from .logging_config import get_logger
from .utils import check_sovits_service, start_gpt_sovits_api

logger = get_logger("voice")


class VoiceManager:
    _STREAM_START = b"__START__"
    _STREAM_END = b"__END__"
    TTS_BUFFERED_FALLBACK_ENV = "TTS_ENABLE_BUFFERED_FALLBACK"
    SYSTEM_TTS_FALLBACK_ENV = "VOICE_ENABLE_SYSTEM_TTS_FALLBACK"
    TTS_TEXT_SPLIT_ENV = "VOICE_TTS_TEXT_SPLIT_METHOD"
    TTS_STREAMING_MODE_ENV = "VOICE_TTS_STREAMING_MODE"
    TTS_PARALLEL_INFER_ENV = "VOICE_TTS_PARALLEL_INFER"
    TTS_MIN_CHUNK_LENGTH_ENV = "VOICE_TTS_MIN_CHUNK_LENGTH"
    TTS_OVERLAP_LENGTH_ENV = "VOICE_TTS_OVERLAP_LENGTH"

    def __init__(self, sovits_url: str = "http://127.0.0.1:9880", ref_audio: str = "", prompt_text: str = "") -> None:
        self.sovits_url = sovits_url
        self.ref_audio = ref_audio
        self.prompt_text = prompt_text
        self._sovits_process = None
        self._bootstrap_attempted = False
        self._bootstrap_lock = threading.Lock()

        self.connect_timeout_sec = int(os.getenv("VOICE_TTS_CONNECT_TIMEOUT_SEC", "5") or "5")
        self.read_timeout_sec = int(os.getenv("VOICE_TTS_READ_TIMEOUT_SEC", "30") or "30")
        self.system_tts_enabled = (os.getenv(self.SYSTEM_TTS_FALLBACK_ENV, "1") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.tts_text_split_method = (os.getenv(self.TTS_TEXT_SPLIT_ENV, "cut1") or "cut1").strip()
        self.tts_streaming_mode = self._read_streaming_mode_env(self.TTS_STREAMING_MODE_ENV, default=3)
        self.tts_parallel_infer = self._read_bool_env(self.TTS_PARALLEL_INFER_ENV, default=False)
        self.tts_min_chunk_length = self._read_int_env(self.TTS_MIN_CHUNK_LENGTH_ENV, default=8, minimum=4)
        self.tts_overlap_length = self._read_int_env(self.TTS_OVERLAP_LENGTH_ENV, default=1, minimum=0)
        self.text_queue: queue.Queue[Optional[str]] = queue.Queue()
        self.audio_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self._audio_cache: dict[str, bytes] = {}
        self._audio_cache_order: deque[str] = deque()
        self._audio_cache_capacity = 24
        self._audio_cache_lock = threading.Lock()

        self._tts_stats_lock = threading.Lock()
        self._tts_stats = self._initial_tts_stats()

        # 验证参考音频是否存在 —— GPT-SoVITS 要求必须提供 `ref_audio_path`，若文件缺失会导致 400 错误。
        self._ref_audio_missing = False
        try:
            if not self.ref_audio or not os.path.exists(self.ref_audio):
                logger.warning(
                    f"TTS reference audio not found: {self.ref_audio!r}. TTS requests will fail with 400 until this is fixed."
                )
                self._ref_audio_missing = True
        except Exception:
            self._ref_audio_missing = True

        if not self._is_sovits_reachable():
            logger.warning("SoVITS 服务当前不可达: %s/tts，已启用本机语音兜底。", self.sovits_url.rstrip("/"))
            self._trigger_sovits_bootstrap_async()

        # 低延迟音频配置
        self.sample_rate = 32000
        self.chunk_size = 256  # 更小的chunk降低延迟

        if not PYAUDIO_AVAILABLE:
            raise ImportError("pyaudio is required for VoiceManager but is not installed.")

        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=self.chunk_size,  # 匹配chunk大小
        )

        # 播放状态控制
        self.is_playing = False
        self.stop_current = threading.Event()

        # 启动工作线程
        threading.Thread(target=self.tts_worker, daemon=True).start()
        threading.Thread(target=self.playback_worker, daemon=True).start()

        # 预热 TTS，减少首句延迟
        threading.Thread(target=self._warmup_tts, daemon=True).start()

    def speak(self, text):
        """发送文本到TTS队列"""
        # 如果正在播放，可以选择打断
        self.text_queue.put(text)

    @staticmethod
    def _read_bool_env(name: str, default: bool = False) -> bool:
        raw_value = os.getenv(name)
        if raw_value is None or raw_value.strip() == "":
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _read_int_env(name: str, default: int, minimum: int = 0) -> int:
        raw_value = os.getenv(name)
        if raw_value is None or raw_value == "":
            return max(minimum, default)

        try:
            value = int(raw_value)
        except ValueError:
            value = default
        return max(minimum, value)

    @staticmethod
    def _read_streaming_mode_env(name: str, default: int = 3) -> Union[int, bool]:
        raw_value = os.getenv(name)
        if raw_value is None or raw_value.strip() == "":
            return default

        normalized = raw_value.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return 2
        if normalized in {"false", "no", "off"}:
            return 0

        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return default

    def _build_tts_params(self, text: str) -> dict:
        """构建 TTS 请求参数，默认使用低延迟流式配置。"""
        return {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": self.ref_audio,
            "prompt_lang": "zh",
            "prompt_text": self.prompt_text,
            "text_split_method": self.tts_text_split_method,
            "media_type": "raw",
            "streaming_mode": self.tts_streaming_mode,
            "parallel_infer": self.tts_parallel_infer,
            "speed_factor": 1.0,
            "min_chunk_length": self.tts_min_chunk_length,
            "overlap_length": self.tts_overlap_length,
        }

    def _build_buffered_tts_params(self, text: str) -> dict:
        """构建稳定的非流式 TTS 请求参数，用于回退和保存。"""
        params = self._build_tts_params(text)
        params["streaming_mode"] = 0
        return params

    @staticmethod
    def _initial_tts_stats() -> dict[str, int]:
        return {
            "stream_attempts": 0,
            "stream_success": 0,
            "stream_empty": 0,
            "stream_errors": 0,
            "buffered_fallback_attempts": 0,
            "buffered_fallback_success": 0,
            "buffered_fallback_empty": 0,
            "buffered_fallback_errors": 0,
            "fallback_skipped_direct_mode": 0,
            "system_tts_fallback_attempts": 0,
            "system_tts_fallback_success": 0,
            "system_tts_fallback_errors": 0,
            "cache_hits": 0,
            "sync_requests": 0,
            "sync_success": 0,
            "sync_empty": 0,
            "sync_errors": 0,
        }

    def _increment_tts_stat(self, key: str) -> None:
        with self._tts_stats_lock:
            self._tts_stats[key] = int(self._tts_stats.get(key, 0)) + 1

    def _is_buffered_fallback_enabled(self) -> bool:
        raw_value = os.environ.get(self.TTS_BUFFERED_FALLBACK_ENV, "1")
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    def reset_tts_stats(self) -> None:
        with self._tts_stats_lock:
            self._tts_stats = self._initial_tts_stats()

    def get_tts_stats(self) -> dict:
        with self._tts_stats_lock:
            stats = dict(self._tts_stats)
        stats["buffered_fallback_enabled"] = self._is_buffered_fallback_enabled()
        stats["system_tts_fallback_enabled"] = bool(getattr(self, "system_tts_enabled", False))
        return stats

    def get_provider_status(self) -> dict:
        return {
            "sovits_url": self.sovits_url,
            "sovits_reachable": self._is_sovits_reachable(),
            "system_tts_fallback_enabled": bool(getattr(self, "system_tts_enabled", False)),
            "bootstrap_attempted": bool(getattr(self, "_bootstrap_attempted", False)),
        }

    def _is_sovits_reachable(self) -> bool:
        docs_url = f"{self.sovits_url.rstrip('/')}/docs"
        return bool(check_sovits_service(docs_url))

    def _trigger_sovits_bootstrap_async(self) -> None:
        lock = getattr(self, "_bootstrap_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._bootstrap_lock = lock

        with lock:
            if bool(getattr(self, "_bootstrap_attempted", False)):
                return
            self._bootstrap_attempted = True

        def _bootstrap() -> None:
            try:
                process = start_gpt_sovits_api(GPT_SOVITS_PATH)
                if process is not None:
                    self._sovits_process = process
                    logger.info("已自动拉起 GPT-SoVITS API 服务")
            except Exception as exc:
                logger.warning("自动拉起 GPT-SoVITS 失败: %s", exc)

        threading.Thread(target=_bootstrap, daemon=True).start()

    def _speak_with_system_tts(self, text: str) -> bool:
        if not bool(getattr(self, "system_tts_enabled", False)):
            return False
        if os.name != "nt":
            return False
        if not text.strip():
            return False

        safe_text = self._sanitize_system_tts_text(text)
        if not safe_text:
            return False

        script = (
            "Add-Type -AssemblyName System.Speech;"
            "[Console]::InputEncoding=[System.Text.Encoding]::UTF8;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$t=[Console]::In.ReadToEnd();"
            "if($t){$s.Speak($t)};"
            "$s.Dispose();"
        )

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                input=safe_text,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
                check=False,
            )
            return completed.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _sanitize_system_tts_text(text: str) -> str:
        cleaned_chars: list[str] = []
        for ch in text or "":
            category = unicodedata.category(ch)
            # Drop private-use/surrogate/unassigned chars and most control chars.
            if category in {"Co", "Cs", "Cn"}:
                continue
            if category.startswith("C") and ch not in {"\n", "\r", "\t"}:
                continue
            cleaned_chars.append(ch)
        return "".join(cleaned_chars).strip()

    @staticmethod
    def _cache_key(text: str) -> str:
        return " ".join((text or "").split())

    def _get_cached_audio(self, text: str) -> Optional[bytes]:
        key = self._cache_key(text)
        if not key:
            return None

        with self._audio_cache_lock:
            cached = self._audio_cache.get(key)
            if cached is None:
                return None

            # LRU refresh
            try:
                self._audio_cache_order.remove(key)
            except ValueError:
                pass
            self._audio_cache_order.append(key)
            self._increment_tts_stat("cache_hits")
            return cached

    def _set_cached_audio(self, text: str, audio_data: bytes) -> None:
        key = self._cache_key(text)
        if not key or not audio_data:
            return

        with self._audio_cache_lock:
            if key in self._audio_cache:
                try:
                    self._audio_cache_order.remove(key)
                except ValueError:
                    pass

            self._audio_cache[key] = audio_data
            self._audio_cache_order.append(key)

            while len(self._audio_cache_order) > self._audio_cache_capacity:
                oldest = self._audio_cache_order.popleft()
                self._audio_cache.pop(oldest, None)

    @staticmethod
    def _raise_for_status_with_body(response: requests.Response, *, context: str) -> None:
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            body_preview = ""
            try:
                body_preview = (response.text or "").strip()
            except Exception:
                body_preview = ""
            if len(body_preview) > 600:
                body_preview = body_preview[:600] + "..."
            logger.error(
                "TTS %s HTTP错误 status=%s body=%s",
                context,
                getattr(response, "status_code", "unknown"),
                body_preview,
            )
            raise

    def _request_tts_audio(self, text: str, *, connect_timeout: int, read_timeout: int) -> bytes:
        tts_data = self._build_buffered_tts_params(text)
        response = self.session.post(
            f"{self.sovits_url}/tts",
            json=tts_data,
            stream=False,
            timeout=(connect_timeout, read_timeout),
        )
        self._raise_for_status_with_body(response, context="buffered")
        return response.content or b""

    def _stream_tts_to_queue(self, text: str, *, connect_timeout: int, read_timeout: int) -> tuple[str, bytes]:
        """流式拉取音频并实时推送到播放队列。"""
        with self.session.post(
            f"{self.sovits_url}/tts",
            json=self._build_tts_params(text),
            stream=True,
            timeout=(connect_timeout, read_timeout),
        ) as resp:
            self._raise_for_status_with_body(resp, context="stream")

            self.audio_queue.put(self._STREAM_START)
            chunk_cache: list[bytes] = []

            for chunk in resp.iter_content(chunk_size=512):
                if self.stop_current.is_set():
                    break
                if chunk:
                    chunk_cache.append(chunk)
                    self.audio_queue.put(chunk)

            if chunk_cache and not self.stop_current.is_set():
                return "success", b"".join(chunk_cache)

            return "empty", b""

    def speak_and_save(self, text: str, wav_path: str) -> bool:
        """
        合成语音并保存到 wav 文件（同步阻塞）

        Args:
            text: 要合成的文本
            wav_path: 保存的 wav 文件路径

        Returns:
            是否成功
        """
        try:
            if self._ref_audio_missing:
                logger.error(
                    f"TTS aborted: reference audio missing ({self.ref_audio}). Place the file or update `REF_AUDIO` in config."
                )
                return False

            audio_data = self._get_cached_audio(text)
            if audio_data is None:
                self._increment_tts_stat("sync_requests")
                audio_data = self._request_tts_audio(
                    text,
                    connect_timeout=self.connect_timeout_sec,
                    read_timeout=max(self.read_timeout_sec, 60),
                )
                if audio_data:
                    self._set_cached_audio(text, audio_data)

            if not audio_data:
                self._increment_tts_stat("sync_empty")
                return False

            self._increment_tts_stat("sync_success")

            # 确保目录存在
            os.makedirs(os.path.dirname(wav_path) if os.path.dirname(wav_path) else ".", exist_ok=True)

            # 保存为 wav 文件
            with wave.open(wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_data)

            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"TTS 网络错误: {e}")
            self._increment_tts_stat("sync_errors")
            return False
        except Exception as e:
            logger.error(f"TTS 保存错误: {e}", exc_info=True)
            self._increment_tts_stat("sync_errors")
            return False

    def play_wav(self, wav_path: str, lip_sync_callback=None):
        """
        播放 wav 文件（阻塞）并可选地进行实时口型同步

        Args:
            wav_path: wav 文件路径
            lip_sync_callback: 口型同步回调函数，接收 0-1 的音量值
        """
        try:
            import numpy as np

            with wave.open(wav_path, "rb") as wav_file:
                # 读取参数
                n_channels = wav_file.getnchannels()
                sampwidth = wav_file.getsampwidth()
                framerate = wav_file.getframerate()

                # --- 优化点 1: 减小 Chunk，降低延迟 ---
                chunk_size = 512  # 从 256 减小到 512，降低延迟

                # 创建临时播放流（如果参数不同）
                if framerate != self.sample_rate or n_channels != 1:
                    temp_stream = self.p.open(
                        format=self.p.get_format_from_width(sampwidth),
                        channels=n_channels,
                        rate=framerate,
                        output=True,
                        frames_per_buffer=chunk_size,
                    )
                    stream = temp_stream
                else:
                    stream = self.stream
                    temp_stream = None

                # 播放
                self.is_playing = True
                self.stop_current.clear()

                # 用于控制发送频率
                update_counter = 0

                data = wav_file.readframes(chunk_size)
                while data and not self.stop_current.is_set():
                    stream.write(data)

                    # --- 优化点 2: 不要每一帧都发指令，降低浏览器负担 ---
                    if lip_sync_callback:
                        update_counter += 1
                        if update_counter % 2 == 0:  # 每 2 个 chunk 发送一次 (降频)
                            try:
                                # 计算音量（RMS）
                                audio_data = np.frombuffer(data, dtype=np.int16)
                                rms = np.sqrt(np.mean(audio_data**2))

                                # --- 优化点 3: 门限过滤 + 非线性映射 ---
                                # 门限过滤 (Gate)：消除底噪；非线性映射：让嘴巴更容易张开
                                volume = 0.0 if rms < 500 else min((rms / 8000) ** 0.8, 1.0)

                                lip_sync_callback(volume)
                            except Exception:
                                pass  # 忽略回调错误，继续播放

                    data = wav_file.readframes(chunk_size)

                # 播放完成，关闭嘴巴
                if lip_sync_callback:
                    lip_sync_callback(0.0)

                self.is_playing = False

                # 关闭临时流
                if temp_stream:
                    temp_stream.stop_stream()
                    temp_stream.close()

        except Exception as e:
            logger.error(f"播放错误: {e}", exc_info=True)
            self.is_playing = False
            if lip_sync_callback:
                lip_sync_callback(0.0)

    def _warmup_tts(self):
        """预热 TTS 服务，触发模型与连接初始化"""
        try:
            if self._ref_audio_missing:
                # 预热时若参考音频缺失，直接返回以避免 400
                return

            warmup_audio = self._request_tts_audio(
                "你好",
                connect_timeout=self.connect_timeout_sec,
                read_timeout=max(10, self.read_timeout_sec),
            )
            if warmup_audio:
                self._set_cached_audio("你好", warmup_audio)
        except Exception:
            pass

    def interrupt(self):
        """打断当前播放"""
        self.stop_current.set()
        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

    def tts_worker(self):
        """TTS请求线程 - 流式获取音频数据"""
        connect_timeout = int(getattr(self, "connect_timeout_sec", 5) or 5)
        read_timeout = int(getattr(self, "read_timeout_sec", 30) or 30)

        while True:
            text = self.text_queue.get()
            if text is None:
                break

            self.stop_current.clear()
            self.is_playing = True

            try:
                cached_audio = self._get_cached_audio(text)
                if cached_audio:
                    self.audio_queue.put(self._STREAM_START)
                    for offset in range(0, len(cached_audio), 512):
                        if self.stop_current.is_set():
                            break
                        self.audio_queue.put(cached_audio[offset : offset + 512])
                    continue

                if self._ref_audio_missing:
                    logger.error(f"TTS request skipped: missing reference audio ({self.ref_audio}).")
                    continue

                stream_status = "error"
                stream_audio = b""

                self._increment_tts_stat("stream_attempts")
                try:
                    stream_status, stream_audio = self._stream_tts_to_queue(
                        text,
                        connect_timeout=connect_timeout,
                        read_timeout=read_timeout,
                    )
                    if stream_status == "success":
                        self._increment_tts_stat("stream_success")
                        self._set_cached_audio(text, stream_audio)
                    else:
                        self._increment_tts_stat("stream_empty")
                except requests.exceptions.RequestException as e:
                    logger.error(f"TTS 流式网络错误: {e}")
                    self._increment_tts_stat("stream_errors")
                    self._trigger_sovits_bootstrap_async()
                except Exception as e:
                    logger.error(f"TTS 流式错误: {e}", exc_info=True)
                    self._increment_tts_stat("stream_errors")
                    self._trigger_sovits_bootstrap_async()

                if stream_status == "success":
                    continue

                if self._is_buffered_fallback_enabled():
                    self._increment_tts_stat("buffered_fallback_attempts")
                    try:
                        fallback_audio = self._request_tts_audio(
                            text,
                            connect_timeout=connect_timeout,
                            read_timeout=read_timeout,
                        )
                        if not fallback_audio:
                            self._increment_tts_stat("buffered_fallback_empty")
                        else:
                            self._increment_tts_stat("buffered_fallback_success")
                            self._set_cached_audio(text, fallback_audio)
                            self.audio_queue.put(self._STREAM_START)
                            for offset in range(0, len(fallback_audio), 512):
                                if self.stop_current.is_set():
                                    break
                                self.audio_queue.put(fallback_audio[offset : offset + 512])
                            continue
                    except requests.exceptions.RequestException as e:
                        logger.error(f"TTS 缓冲回退网络错误: {e}")
                        self._increment_tts_stat("buffered_fallback_errors")
                        self._trigger_sovits_bootstrap_async()
                    except Exception as e:
                        logger.error(f"TTS 缓冲回退错误: {e}", exc_info=True)
                        self._increment_tts_stat("buffered_fallback_errors")
                        self._trigger_sovits_bootstrap_async()
                else:
                    self._increment_tts_stat("fallback_skipped_direct_mode")

                self._increment_tts_stat("system_tts_fallback_attempts")
                if self._speak_with_system_tts(text):
                    logger.info("SoVITS 不可用，已使用系统 TTS 兜底播报")
                    self._increment_tts_stat("system_tts_fallback_success")
                    continue
                self._increment_tts_stat("system_tts_fallback_errors")

            except requests.exceptions.RequestException as e:
                logger.error(f"TTS 网络错误: {e}")
            except Exception as e:
                logger.error(f"TTS 错误: {e}", exc_info=True)
            finally:
                # 发送结束标记
                self.audio_queue.put(self._STREAM_END)
                self.text_queue.task_done()

    def playback_worker(self):
        """音频播放线程 - 低延迟播放"""
        buffer = b""
        min_buffer_size = 256  # 最小缓冲大小，收到这么多数据就开始播放
        immediate_first_packet = False

        while True:
            try:
                # 非阻塞获取，适当放大超时以减少 CPU 空转（原 0.01s 过于激进）
                chunk = self.audio_queue.get(timeout=0.05)

                if chunk is None:
                    break

                if chunk == self._STREAM_END:
                    # 播放剩余buffer
                    if buffer:
                        self.stream.write(buffer)
                        buffer = b""
                    self.is_playing = False
                    self.audio_queue.task_done()
                    continue

                if chunk == self._STREAM_START:
                    buffer = b""
                    immediate_first_packet = True
                    self.audio_queue.task_done()
                    continue

                if immediate_first_packet:
                    self.stream.write(chunk)
                    immediate_first_packet = False
                elif len(chunk) >= min_buffer_size:
                    self.stream.write(chunk)
                else:
                    buffer += chunk

                # 达到最小缓冲就开始播放
                while len(buffer) >= min_buffer_size:
                    self.stream.write(buffer[:min_buffer_size])
                    buffer = buffer[min_buffer_size:]

                self.audio_queue.task_done()

            except queue.Empty:
                # 队列为空时，播放剩余buffer（如果有）
                if buffer and len(buffer) >= 128:
                    write_size = min(len(buffer), min_buffer_size)
                    self.stream.write(buffer[:write_size])
                    buffer = buffer[write_size:]
                continue

    def close(self):
        """关闭语音管理器"""
        self.text_queue.put(None)
        self.audio_queue.put(None)
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
        process = getattr(self, "_sovits_process", None)
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

    # ==================== 异步接口 ====================

    async def speak_async(self, text: str):
        """异步版 speak — 在线程池中执行 TTS。"""
        import asyncio

        await asyncio.to_thread(self.speak, text)

    async def speak_and_save_async(self, text: str, wav_path: str) -> bool:
        """异步版 speak_and_save — 在线程池中执行 TTS 合成。"""
        import asyncio

        return await asyncio.to_thread(self.speak_and_save, text, wav_path)
