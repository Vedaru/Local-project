"""
modules/ear.py

实现一个基于 PyAudio + faster-whisper 的听觉模块（Ear），
- 使用 CUDA 加速的 faster-whisper 模型 (device='cuda', compute_type='float16')
- 使用 RMS 做简单的 VAD（静音检测）
- 支持内存中处理（也可写入临时 wav 文件）

注意：使用此模块前请确保已安装 GPU 版本的 PyTorch（对应本机 CUDA 版本），
并且安装了 requirements.txt 中列出的依赖。
"""

import os
import time
import wave
import tempfile
import threading
import re
import sys

import numpy as np
import pyaudio
import torch

# 必须首先导入补丁模块（修复 ctranslate2 的 ROCm 路径问题）
from . import _patch_ctranslate2

# 现在可以安全导入 faster_whisper
from faster_whisper import WhisperModel

# 检查 CUDA 可用性
CUDA_AVAILABLE = torch.cuda.is_available()


class Ear:
    """
    听觉模块：从麦克风监听并将语音片段实时转写为文本。

    使用方式示例：
        ear = Ear(model_size='base')
        try:
            ear.listen(callback=lambda text: print("识别到：", text))
        finally:
            ear.close()

    重要参数：
    - threshold: RMS 阈值（默认 500）用于判定有语音
    - end_silence: 低于阈值连续 N 秒视为说话结束（默认 1.5s）
    - sample_rate: 采样率，推荐 16000
    - chunk_size: 每次读入样本点数
    - max_record_seconds: 单次最大录音长度，防止无限录制
    """

    def __init__(
        self,
        model_size: str = "base",
        threshold: float = 500.0,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        end_silence: float = 1.5,
        max_record_seconds: float = 30.0,
    ):
        """初始化并加载 faster-whisper 模型到 GPU。"""
        self.model_size = model_size
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.end_silence = end_silence
        self.max_record_seconds = max_record_seconds

        # PyAudio / 流
        self.pa = pyaudio.PyAudio()
        self.stream = None

        # VAD/录音状态
        self._recording = False
        self._running = False

        # 临时目录
        self.temp_dir = os.path.join(os.path.dirname(__file__), "..", "data", "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 清理旧的临时文件
        self._cleanup_old_temp_files()

        # 强制使用 GPU（不自动降级到 CPU）
        if not CUDA_AVAILABLE:
            raise RuntimeError(
                "[Ear] 错误：CUDA 不可用。请检查：\n"
                "  1. NVIDIA GPU 驱动是否已安装\n"
                "  2. torch.cuda.is_available() 是否返回 True\n"
                "  3. PyTorch 是否安装了 GPU 版本\n"
                "\n提示：坚持使用 GPU，不使用 CPU。"
            )
        
        device = "cuda"
        compute_type = "float16"
        print(f"[Ear] 正在加载 faster-whisper 模型: {model_size}, device={device}, compute_type={compute_type} ...")
        
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            print("[Ear] 模型加载完成（GPU 模式，仅支持 CUDA）。")
        except (RuntimeError, OSError) as e:
            raise RuntimeError(
                f"[Ear] 错误：加载模型失败（GPU 模式下仅支持 CUDA）。\n"
                f"原始错误: {e}\n"
                f"请检查 CUDA 环境和驱动。"
            )

    def _open_stream(self):
        if self.stream is None:
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
            )

    def _close_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def _cleanup_old_temp_files(self):
        """清理临时目录中的所有旧的 .wav 文件"""
        try:
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    if filename.endswith('.wav'):
                        filepath = os.path.join(self.temp_dir, filename)
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass  # 忽略单个文件删除错误
                print(f"[Ear] 初始化时清理了临时音频目录")
        except Exception:
            pass  # 如果清理失败，不影响初始化

    def _write_wav(self, frames: bytes, path: str):
        """将原始 PCM bytes 写入 wav 文件（16-bit 单声道）"""
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 -> 2 bytes
            wf.setframerate(self.sample_rate)
            wf.writeframes(frames)

    def transcribe(self, audio_np: np.ndarray) -> str:
        """
        使用 faster-whisper 转录音频片段（语言设定为中文）。
        输入：audio_np 为 np.float32 数组，取值范围约 [-1, 1]，采样率为 self.sample_rate。
        返回：识别出的文本（已过滤空或幻觉结果），如果无有效文本，返回空字符串。
        """
        try:
            # faster-whisper 的 transcribe 接口会返回 (segments, info)
            # 指定语言为中文 (language="zh")
            segments, _ = self.model.transcribe(audio_np, language="zh", beam_size=5)
            text = "".join([seg.text for seg in segments]).strip()

            # 过滤空文本或明显的系统幻觉（例如以括号起始的系统提示）
            if not text:
                return ""

            # 如果文本看起来像 (System) ... 或仅包含控制符/标点，认为是幻觉 -> 过滤
            if re.match(r"^\s*\(.*\)", text) or re.match(r"^[^\w\u4e00-\u9fff]+$", text):
                return ""

            return text

        except Exception as e:
            # GPU 模式下推理失败，直接抛出异常而不静默处理
            raise RuntimeError(
                f"[Ear] 错误：GPU 推理失败。\n"
                f"原始错误: {e}\n"
                f"\n常见原因：\n"
                f"  - cublas64_*.dll 未找到：检查 CUDA 驱动和工具包安装\n"
                f"  - 显存不足：尝试重启应用或关闭其他 GPU 应用\n"
                f"  - GPU 驱动过旧：更新到最新版本\n"
                f"\n当前要求：仅使用 GPU，不降级到 CPU。"
            )

    def listen(self, callback=None):
        """
        开始阻塞监听麦克风并基于 RMS 做 VAD。

        callback: 一个可选回调，签名为 callback(text: str)。
                  当检测到一句话并转写完成后会被调用。
        这是阻塞调用，按 Ctrl+C 或 调用 stop() 停止。
        """
        self._open_stream()
        self._running = True
        print("[Ear] 开始监听麦克风，按 Ctrl+C 停止。")

        frames = []  # 临时存放 bytes
        last_voice_time = None
        start_time = None

        try:
            while self._running:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))

                now = time.time()

                if not self._recording:
                    # 检测语音开始
                    if rms > self.threshold:
                        self._recording = True
                        frames = [data]
                        last_voice_time = now
                        start_time = now
                        print("[Ear] 语音开始，开始录制...")
                else:
                    # 已在录制状态
                    frames.append(data)
                    if rms > self.threshold:
                        last_voice_time = now

                    # 结束条件：末次检测到语音距离当前超过 end_silence，或超出最长录制时间
                    if (now - last_voice_time) >= self.end_silence or (now - start_time) >= self.max_record_seconds:
                        print("[Ear] 检测到语音结束，准备转写...")

                        # 合并 bytes 并转为 numpy float32（范围 -1..1）
                        raw = b"".join(frames)
                        ints = np.frombuffer(raw, dtype=np.int16)
                        audio_float32 = (ints.astype(np.float32) / 32768.0).astype(np.float32)

                        # 可选：将音频保存为临时 wav（如果需要调试或外部工具使用）
                        tmp_wav = None
                        try:
                            tmp_wav = os.path.join(self.temp_dir, f"input_{int(time.time()*1000)}.wav")
                            self._write_wav(raw, tmp_wav)
                        except Exception as e:
                            print(f"[Ear] 保存临时音频失败: {e}")
                            tmp_wav = None

                        # 转写
                        try:
                            text = self.transcribe(audio_float32)
                            if text:
                                print(f"[Ear] 转写结果: {text}")
                                if callback:
                                    try:
                                        callback(text)
                                    except Exception as e:
                                        print(f"[Ear] 回调函数出错: {e}")
                            else:
                                print("[Ear] 未识别出有效文本（可能为噪声或模型幻觉被过滤）")
                        finally:
                            # 对话完成后立即删除临时音频文件
                            if tmp_wav and os.path.exists(tmp_wav):
                                try:
                                    os.remove(tmp_wav)
                                    print(f"[Ear] 已删除临时音频: {os.path.basename(tmp_wav)}")
                                except Exception as e:
                                    print(f"[Ear] 删除临时音频失败: {e}")

                        # 重置状态，准备下一句
                        self._recording = False
                        frames = []
                        last_voice_time = None
                        start_time = None

        except KeyboardInterrupt:
            print("[Ear] 用户中断，停止监听。")
        except Exception as e:
            print(f"[Ear] 监听出错: {e}")
        finally:
            self._close_stream()

    def stop(self):
        """停止 listen 循环（线程或外部控制时使用）"""
        self._running = False

    def close(self):
        """释放资源并尽可能释放显存"""
        print("[Ear] 正在释放资源...")
        try:
            self._close_stream()
            if self.pa is not None:
                try:
                    self.pa.terminate()
                except Exception:
                    pass
        except Exception:
            pass

        # 删除模型并释放 GPU 显存
        try:
            del self.model
            torch.cuda.empty_cache()
            print("[Ear] 已释放模型并清理 GPU 显存。")
        except Exception as e:
            print(f"[Ear] 释放模型时出现异常: {e}")

    # 支持上下文管理
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
