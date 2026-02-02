"""
口型同步模块 - 基于音频或文本分析的口型动画
"""

import math
import time
import threading
import wave
import struct
from typing import Callable, Optional, List
from pathlib import Path
from dataclasses import dataclass

from .logger import log_info, log_debug, log_warning


@dataclass
class LipSyncFrame:
    """口型同步帧"""
    value: float  # 嘴巴开合度 0.0-1.0
    timestamp: float  # 时间戳


class LipSyncAnalyzer:
    """口型同步分析器 - 分析音频生成口型数据"""
    
    # 音素到口型的映射（简化版）
    PHONEME_MAP = {
        # 元音 - 嘴巴张开
        'a': 0.9, 'o': 0.8, 'e': 0.6, 'i': 0.4, 'u': 0.3,
        'ā': 0.9, 'ō': 0.8, 'ē': 0.6, 'ī': 0.4, 'ū': 0.3,
        'á': 0.9, 'ó': 0.8, 'é': 0.6, 'í': 0.4, 'ú': 0.3,
        'à': 0.9, 'ò': 0.8, 'è': 0.6, 'ì': 0.4, 'ù': 0.3,
        # 辅音 - 嘴巴较小
        'b': 0.2, 'p': 0.2, 'm': 0.2,  # 双唇音
        'f': 0.3, 'v': 0.3,  # 唇齿音
        'd': 0.4, 't': 0.4, 'n': 0.4, 'l': 0.4,  # 舌尖音
        'g': 0.3, 'k': 0.3, 'h': 0.5,  # 舌根音
        'j': 0.4, 'q': 0.4, 'x': 0.4,  # 舌面音
        'z': 0.3, 'c': 0.3, 's': 0.3,  # 舌尖前音
        'zh': 0.4, 'ch': 0.4, 'sh': 0.4, 'r': 0.4,  # 舌尖后音
        # 默认
        ' ': 0.0, '，': 0.0, '。': 0.0, '！': 0.0, '？': 0.0,
    }
    
    def __init__(self):
        self._frames: List[LipSyncFrame] = []
    
    def analyze_text(self, text: str, duration_per_char: float = 0.15) -> List[LipSyncFrame]:
        """
        基于文本分析生成口型数据
        
        Args:
            text: 要分析的文本
            duration_per_char: 每个字符的持续时间（秒）
        
        Returns:
            口型帧列表
        """
        frames = []
        timestamp = 0.0
        
        for char in text:
            char_lower = char.lower()
            
            # 获取口型值
            if char_lower in self.PHONEME_MAP:
                value = self.PHONEME_MAP[char_lower]
            elif '\u4e00' <= char <= '\u9fff':  # 中文字符
                # 中文字符默认较大的口型
                value = 0.6 + (hash(char) % 30) / 100  # 0.6-0.9 之间随机
            else:
                value = 0.0
            
            # 生成平滑的帧（每个字符多个帧）
            frames_per_char = max(1, int(duration_per_char / 0.03))
            for i in range(frames_per_char):
                # 使用正弦曲线平滑
                progress = i / frames_per_char
                smooth_value = value * math.sin(progress * math.pi)
                frames.append(LipSyncFrame(
                    value=smooth_value,
                    timestamp=timestamp
                ))
                timestamp += 0.03
            
            # 短暂闭嘴
            frames.append(LipSyncFrame(value=0.1, timestamp=timestamp))
            timestamp += 0.02
        
        # 结束时闭嘴
        frames.append(LipSyncFrame(value=0.0, timestamp=timestamp))
        
        self._frames = frames
        log_debug(f"Generated {len(frames)} lip sync frames for text ({len(text)} chars)")
        return frames
    
    def analyze_audio(self, audio_path: str, sample_rate: int = 16000) -> List[LipSyncFrame]:
        """
        基于音频分析生成口型数据
        
        Args:
            audio_path: 音频文件路径
            sample_rate: 采样率
        
        Returns:
            口型帧列表
        """
        frames = []
        
        try:
            with wave.open(audio_path, 'rb') as wav:
                n_channels = wav.getnchannels()
                sampwidth = wav.getsampwidth()
                framerate = wav.getframerate()
                n_frames = wav.getnframes()
                
                # 每帧分析的采样数（约30ms一帧）
                samples_per_frame = int(framerate * 0.03)
                
                total_frames = n_frames // samples_per_frame
                timestamp = 0.0
                
                for _ in range(total_frames):
                    raw_data = wav.readframes(samples_per_frame)
                    if len(raw_data) < samples_per_frame * sampwidth * n_channels:
                        break
                    
                    # 计算音量（RMS）
                    if sampwidth == 2:
                        fmt = f'<{samples_per_frame * n_channels}h'
                        samples = struct.unpack(fmt, raw_data)
                    else:
                        samples = list(raw_data)
                    
                    # 计算 RMS
                    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                    
                    # 归一化到 0-1（假设16位音频，最大值32767）
                    max_val = 32767 if sampwidth == 2 else 255
                    normalized = min(1.0, rms / (max_val * 0.3))
                    
                    frames.append(LipSyncFrame(
                        value=normalized,
                        timestamp=timestamp
                    ))
                    timestamp += 0.03
                
                log_debug(f"Analyzed audio: {len(frames)} frames from {audio_path}")
                
        except Exception as e:
            log_warning(f"Failed to analyze audio: {e}")
            # 返回空帧
            frames = [LipSyncFrame(value=0.0, timestamp=0.0)]
        
        self._frames = frames
        return frames


class LipSyncPlayer:
    """口型同步播放器 - 实时播放口型动画"""
    
    def __init__(self, update_callback: Callable[[float], None]):
        """
        Args:
            update_callback: 口型更新回调函数，接收一个 0-1 的值
        """
        self._callback = update_callback
        self._playing = False
        self._thread: Optional[threading.Thread] = None
        self._frames: List[LipSyncFrame] = []
        self._stop_event = threading.Event()
    
    def play(self, frames: List[LipSyncFrame], blocking: bool = False):
        """
        播放口型动画
        
        Args:
            frames: 口型帧列表
            blocking: 是否阻塞等待播放完成
        """
        self._frames = frames
        self._stop_event.clear()
        self._playing = True
        
        if blocking:
            self._play_frames()
        else:
            self._thread = threading.Thread(target=self._play_frames, daemon=True)
            self._thread.start()
    
    def _play_frames(self):
        """播放帧序列"""
        if not self._frames:
            log_debug("No frames to play")
            return
        
        log_debug(f"Starting lip sync playback: {len(self._frames)} frames")
        start_time = time.time()
        frame_index = 0
        last_log_time = 0
        
        while frame_index < len(self._frames) and not self._stop_event.is_set():
            current_time = time.time() - start_time
            frame = self._frames[frame_index]
            
            if current_time >= frame.timestamp:
                self._callback(frame.value)
                frame_index += 1
                
                # 每秒记录一次日志
                if current_time - last_log_time >= 1.0:
                    log_debug(f"Lip sync progress: frame {frame_index}/{len(self._frames)}, value={frame.value:.2f}")
                    last_log_time = current_time
            else:
                time.sleep(0.01)
        
        # 播放完成，闭嘴
        log_debug(f"Lip sync playback finished after {time.time() - start_time:.2f}s")
        self._callback(0.0)
        self._playing = False
    
    def stop(self):
        """停止播放"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._playing = False
        self._callback(0.0)
    
    @property
    def is_playing(self) -> bool:
        return self._playing


class LipSyncManager:
    """口型同步管理器 - 统一的口型同步接口"""
    
    def __init__(self, update_callback: Callable[[float], None]):
        """
        Args:
            update_callback: 口型更新回调函数
        """
        self._analyzer = LipSyncAnalyzer()
        self._player = LipSyncPlayer(update_callback)
        log_info("LipSyncManager initialized")
    
    def sync_with_text(self, text: str, duration_per_char: float = 0.12, blocking: bool = False):
        """
        基于文本的口型同步
        
        Args:
            text: 文本内容
            duration_per_char: 每个字符的持续时间
            blocking: 是否阻塞
        """
        frames = self._analyzer.analyze_text(text, duration_per_char)
        self._player.play(frames, blocking=blocking)
    
    def sync_with_audio(self, audio_path: str, blocking: bool = False):
        """
        基于音频的口型同步
        
        Args:
            audio_path: 音频文件路径
            blocking: 是否阻塞
        """
        frames = self._analyzer.analyze_audio(audio_path)
        self._player.play(frames, blocking=blocking)
    
    def stop(self):
        """停止口型同步"""
        self._player.stop()
    
    @property
    def is_playing(self) -> bool:
        return self._player.is_playing
