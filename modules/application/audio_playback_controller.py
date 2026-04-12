"""
AudioPlaybackController — 音频播放 + LipSync 驱动

从 LocalProjectApplication 中提取，负责:
- TTS speak 请求处理（wav 文件播放 → 音量驱动嘴型 → 文本降级）
- pyaudio 播放线程管理
"""

import threading
import time
from pathlib import Path
from typing import Any, Optional

from modules.avatar import LipSyncManager
from modules.logging_config import get_logger
from modules.utils import sanitize_dialogue_text

logger = get_logger("AudioPlaybackController")

# 最近种子文本复用窗口（秒）
EXPRESSION_SEED_REUSE_WINDOW_SEC = 1.2
AUDIO_FADE_MS = 8
AUDIO_FRAMES_PER_BUFFER = 512
AUDIO_RMS_THRESHOLD = 500.0
AUDIO_RMS_NORMALIZER = 8000.0
AUDIO_VOLUME_EXPONENT = 0.8
AUDIO_LIPSYNC_UPDATE_INTERVAL = 2


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

        if isinstance(payload, dict):
            text = str(payload.get("text") or "").strip()
            wav_path = str(payload.get("wav_path") or "").strip()
            tts_status = str(payload.get("status") or "").strip()
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
        if isinstance(payload, dict):
            playlist = self._extract_wav_playlist(payload)
            if len(playlist) >= 2:
                try:
                    self._play_audio_segments_with_lipsync(playlist)
                    logger.info(f"[LipSync] 启动分片无缝播放: segments={len(playlist)}")
                    return
                except Exception as exc:
                    logger.warning(f"[LipSync] 分片无缝播放失败，回退单wav: {exc}")

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

    @staticmethod
    def _extract_wav_playlist(payload: dict[str, Any]) -> list[str]:
        segments = payload.get("segments")
        if not isinstance(segments, list):
            return []

        wavs: list[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            wav_path = str(segment.get("wav_path") or "").strip()
            if not wav_path:
                continue
            if Path(wav_path).exists():
                wavs.append(wav_path)
        return wavs

    @staticmethod
    def _apply_edge_fade_pcm16(
        pcm_data: bytes,
        channels: int,
        sample_rate: int,
        *,
        fade_ms: int = 8,
        fade_in: bool,
        fade_out: bool,
    ) -> bytes:
        if not pcm_data or channels <= 0 or sample_rate <= 0:
            return pcm_data
        if len(pcm_data) % 2 != 0:
            return pcm_data

        import struct

        samples = list(struct.unpack(f"<{len(pcm_data) // 2}h", pcm_data))
        if not samples:
            return pcm_data

        frame_count = len(samples) // channels
        if frame_count <= 0:
            return pcm_data

        fade_frames = int(sample_rate * max(1, fade_ms) / 1000)
        fade_frames = max(1, min(fade_frames, frame_count // 2))

        if fade_in:
            for i in range(fade_frames):
                gain = float(i + 1) / float(fade_frames)
                frame_base = i * channels
                for ch in range(channels):
                    idx = frame_base + ch
                    samples[idx] = int(samples[idx] * gain)

        if fade_out:
            for i in range(fade_frames):
                gain = float(fade_frames - i) / float(fade_frames)
                frame_base = (frame_count - fade_frames + i) * channels
                for ch in range(channels):
                    idx = frame_base + ch
                    samples[idx] = int(samples[idx] * gain)

        return struct.pack(f"<{len(samples)}h", *samples)

    @staticmethod
    def _compute_lipsync_volume_from_pcm16(samples: tuple[int, ...]) -> float:
        if not samples:
            return 0.0
        import math

        rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
        if rms <= AUDIO_RMS_THRESHOLD:
            return 0.0
        return float(min((rms / AUDIO_RMS_NORMALIZER) ** AUDIO_VOLUME_EXPONENT, 1.0))

    @staticmethod
    def _open_output_stream(pa: Any, stream: Any, sampwidth: int, channels: int, framerate: int) -> tuple[Any, Any]:
        if stream is not None:
            return pa, stream

        import pyaudio

        if pa is None:
            pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pa.get_format_from_width(sampwidth),
            channels=channels,
            rate=framerate,
            output=True,
            frames_per_buffer=AUDIO_FRAMES_PER_BUFFER,
        )
        return pa, stream

    @staticmethod
    def _cleanup_output_stream(pa: Any, stream: Any) -> None:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        if pa is not None:
            pa.terminate()

    def _stream_segment_and_drive_lipsync(self, stream: Any, raw_data: bytes, sampwidth: int, channels: int) -> None:
        if not raw_data:
            return

        manager = self._lip_sync_manager
        if manager is None:
            return

        import struct

        chunk_size = max(2, AUDIO_FRAMES_PER_BUFFER * max(1, sampwidth) * max(1, channels))
        update_counter = 0
        for offset in range(0, len(raw_data), chunk_size):
            chunk = raw_data[offset: offset + chunk_size]
            if not chunk:
                continue
            stream.write(chunk)
            update_counter += 1
            if sampwidth != 2 or update_counter % AUDIO_LIPSYNC_UPDATE_INTERVAL != 0:
                continue

            fmt = f"<{len(chunk) // 2}h"
            samples = struct.unpack(fmt, chunk)
            volume = self._compute_lipsync_volume_from_pcm16(samples)
            manager._player._callback(volume)

    def _play_audio_segments_with_lipsync(self, wav_paths: list[str]) -> None:
        """Play multiple wav files on one output stream to reduce gaps/clicks."""
        if not self._lip_sync_manager or not wav_paths:
            return

        import wave as _wave

        def _worker() -> None:
            manager = self._lip_sync_manager
            if manager is None:
                return
            pa = None
            stream = None
            try:
                total_segments = len(wav_paths)

                for idx, wav_path in enumerate(wav_paths):
                    with _wave.open(wav_path, "rb") as wf:
                        n_channels = int(wf.getnchannels() or 1)
                        sampwidth = int(wf.getsampwidth() or 2)
                        framerate = int(wf.getframerate() or 32000)
                        pa, stream = self._open_output_stream(pa, stream, sampwidth, n_channels, framerate)

                        raw_data = wf.readframes(int(wf.getnframes() or 0))
                        if sampwidth == 2 and raw_data:
                            raw_data = self._apply_edge_fade_pcm16(
                                raw_data,
                                channels=n_channels,
                                sample_rate=framerate,
                                fade_ms=AUDIO_FADE_MS,
                                fade_in=(idx > 0),
                                fade_out=(idx < total_segments - 1),
                            )

                        self._stream_segment_and_drive_lipsync(stream, raw_data, sampwidth, n_channels)

                manager._player._callback(0.0)
                self._cleanup_output_stream(pa, stream)
            except Exception:
                manager._player._callback(0.0)
                try:
                    self._cleanup_output_stream(pa, stream)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _play_audio_with_lipsync(self, wav_path: str) -> None:
        """Python 端 pyaudio 播放 + LipSyncManager 驱动嘴型（纯本地方案）。"""
        if not self._lip_sync_manager:
            return

        import wave as _wave

        def _worker() -> None:
            manager = self._lip_sync_manager
            if manager is None:
                return
            try:
                with _wave.open(wav_path, "rb") as wf:
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    framerate = wf.getframerate()
                    frames_per_buffer = AUDIO_FRAMES_PER_BUFFER

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
                        if update_counter % AUDIO_LIPSYNC_UPDATE_INTERVAL == 0:
                            # 计算 RMS 音量值驱动嘴型
                            import struct
                            fmt = f"<{len(data) // sampwidth}h" if sampwidth == 2 else None
                            if fmt:
                                samples = struct.unpack(fmt, data)
                                volume = self._compute_lipsync_volume_from_pcm16(samples)
                                manager._player._callback(volume)
                        data = wf.readframes(frames_per_buffer)

                    # 播放完成，闭嘴
                    manager._player._callback(0.0)
                    stream.stop_stream()
                    stream.close()
                    pa.terminate()
            except Exception:
                manager._player._callback(0.0)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def cleanup(self):
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0
