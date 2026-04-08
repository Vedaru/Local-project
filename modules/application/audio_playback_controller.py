"""
AudioPlaybackController — 音频播放 + LipSync 驱动

从 LocalProjectApplication 中提取，负责:
- TTS speak 请求处理（wav 文件播放 → 音量驱动嘴型 → 文本降级）
- pyaudio 播放线程管理
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from modules.avatar import LipSyncManager
from modules.logging_config import get_logger
from modules.utils import sanitize_dialogue_text

logger = get_logger("AudioPlaybackController")

# 最近种子文本复用窗口（秒）
EXPRESSION_SEED_REUSE_WINDOW_SEC = 1.2


class AudioPlaybackController:
    """Manages audio playback with lip-sync integration and graceful fallback."""

    def __init__(self, lip_sync_manager: Optional[LipSyncManager]):
        self._lip_sync_manager = lip_sync_manager
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0

    @property
    def pending_expression_text(self) -> str:
        return self._pending_expression_text

    @pending_expression_text.setter
    def pending_expression_text(self, value: str):
        self._pending_expression_text = value

    @property
    def last_expression_seed_text(self) -> str:
        return self._last_expression_seed_text

    @property
    def last_expression_seed_at(self) -> float:
        return self._last_expression_seed_at

    def on_speak_request(
        self,
        payload: object,
        expression_orchestrator=None,
    ) -> None:
        """
        TTS请求优先走真实音频驱动嘴型，缺失wav时再降级文本驱动。

        Args:
            payload: dict(text, wav_path, status, duration_sec) or plain str
            expression_orchestrator: Optional ExpressionOrchestrator for triggering expression flow
        """
        if not self._lip_sync_manager:
            return

        text = ""
        wav_path = ""
        tts_status = ""
        duration_sec: Optional[float] = None

        if isinstance(payload, dict):
            text = str(payload.get("text") or "").strip()
            wav_path = str(payload.get("wav_path") or "").strip()
            tts_status = str(payload.get("status") or "").strip()
            raw_duration = payload.get("duration_sec")
            if isinstance(raw_duration, (int, float)) and raw_duration > 0:
                duration_sec = float(raw_duration)
        elif isinstance(payload, str):
            text = payload.strip()

        now = time.monotonic()
        expression_text = self._pending_expression_text or sanitize_dialogue_text(text)
        self._pending_expression_text = ""

        # 触发表情时间线（如果提供了 orchestrator 且有有效文本）
        if expression_orchestrator is not None:
            if expression_text:
                recently_seeded = (
                    expression_text == expression_orchestrator.last_expression_seed_text
                    and (now - expression_orchestrator.last_expression_seed_at) < EXPRESSION_SEED_REUSE_WINDOW_SEC
                )
                if not recently_seeded:
                    expression_orchestrator.on_expression_change(expression_text)
            else:
                # 无可分析文本时主动触发中性回退，防止卡在上一轮情绪。
                expression_orchestrator.on_expression_change("")

        # 优先：wav 音频驱动嘴型
        if wav_path:
            wav_file = Path(wav_path)
            if wav_file.exists():
                try:
                    self._play_audio_with_lipsync(str(wav_file))
                    logger.info(f"[LipSync] Python音频+嘴型启动: {wav_file.name}")
                    return
                except Exception as exc:
                    logger.warning(f"[LipSync] 音频驱动失败，回退文本驱动: {exc}")
            else:
                logger.warning(f"[LipSync] 收到的wav文件不存在: {wav_file}")

        # 降级：文本驱动嘴型
        if not text:
            return

        try:
            self._lip_sync_manager.sync_with_text(
                text, duration_per_char=0.2, blocking=False
            )
            logger.warning(
                f"[LipSync] 已降级为文本驱动 (tts_status={tts_status or 'unknown'})"
            )
        except Exception as exc:
            logger.warning(f"[LipSync] 文本驱动失败: {exc}")

    def _play_audio_with_lipsync(self, wav_path: str) -> None:
        """Python 端 pyaudio 播放 + LipSyncManager 驱动嘴型（纯本地方案）。"""
        if not self._lip_sync_manager:
            return

        import wave as _wave

        def _worker():
            try:
                with _wave.open(wav_path, "rb") as wf:
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    framerate = wf.getframerate()
                    frames_per_buffer = 512

                    import pyaudio
                    pa = pyaudio.PyAudio()
                    stream = pa.open(
                        format=pa.get_format_from_width(sampwidth),
                        channels=n_channels,
                        rate=framerate,
                        output=True,
                        frames_per_buffer=frames_per_buffer,
                    )

                    update_counter = 0
                    data = wf.readframes(frames_per_buffer)
                    while data:
                        stream.write(data)
                        update_counter += 1
                        if update_counter % 2 == 0:
                            # 计算 RMS 音量值驱动嘴型
                            import struct, math
                            fmt = f"<{len(data) // sampwidth}h" if sampwidth == 2 else None
                            if fmt:
                                samples = struct.unpack(fmt, data)
                                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                                volume = min((rms / 8000.0) ** 0.8, 1.0) if rms > 500 else 0.0
                                self._lip_sync_manager._player._callback(volume)
                        data = wf.readframes(frames_per_buffer)

                    # 播放完成，闭嘴
                    self._lip_sync_manager._player._callback(0.0)
                    stream.stop_stream()
                    stream.close()
                    pa.terminate()
            except Exception:
                self._lip_sync_manager._player._callback(0.0)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def cleanup(self):
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0
