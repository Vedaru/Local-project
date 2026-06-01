"""
AudioPlaybackController — 音频播放 + LipSync 驱动

从 LocalProjectApplication 中提取，负责:
- TTS speak 请求处理（wav 文件播放 → 音量驱动嘴型 → 文本降级）
- pyaudio 播放线程管理
"""

import os
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
# 段间淡出（仅多段拼接；不对首段 fade-in，避免吞字）
AUDIO_SEGMENT_FADE_MS = 4
# 新开输出流时写入极短静音，减轻设备冷启动丢首帧（不宜过长）
AUDIO_PREBUFFER_MS = 30
# 冷启动后首句 TTS 使用更长预缓冲，减轻「开头被吞」
AUDIO_FIRST_PLAY_PREBUFFER_MS = 120
AUDIO_WARMUP_SILENCE_MS = 100
AUDIO_WAV_DELETE_RETRIES = 8
AUDIO_WAV_DELETE_RETRY_DELAY_SEC = 0.12
AUDIO_FRAMES_PER_BUFFER = 512
AUDIO_RMS_THRESHOLD = 320.0
AUDIO_RMS_NORMALIZER = 8000.0
AUDIO_VOLUME_EXPONENT = 0.8
AUDIO_LIPSYNC_UPDATE_INTERVAL = 2


class AudioPlaybackController:
    """Manages audio playback with lip-sync integration and graceful fallback."""

    def __init__(
        self,
        lip_sync_manager: Optional[LipSyncManager],
        *,
        avatar_widget: Any = None,
        delete_wav_after_playback: bool = True,
    ):
        self._lip_sync_manager = lip_sync_manager
        self._avatar_widget = avatar_widget
        self._delete_wav_after_playback = bool(delete_wav_after_playback)
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0
        self._play_generation = 0
        self._audio_output_warmed = False
        self._needs_first_play_prebuffer = True

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

    def _is_playback_cancelled(self, generation: int) -> bool:
        return generation != self._play_generation

    def _start_playback_worker(self, worker) -> None:
        """递增世代号以取消旧播放；避免 join 与新线程抢停导致整段无声。"""
        self._play_generation += 1
        generation = self._play_generation

        def _wrapped() -> None:
            try:
                worker(generation)
            except Exception:
                logger.exception("[LipSync] 音频播放线程异常")
            finally:
                if not self._is_playback_cancelled(generation):
                    manager = self._lip_sync_manager
                    if manager is not None:
                        manager._player._callback(0.0)

        threading.Thread(
            target=_wrapped,
            daemon=True,
            name="audio-lipsync-playback",
        ).start()

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

        if expression_orchestrator is not None:
            if expression_text:
                recently_seeded = (
                    expression_text == expression_orchestrator.last_expression_seed_text
                    and (now - expression_orchestrator.last_expression_seed_at) < EXPRESSION_SEED_REUSE_WINDOW_SEC
                )
                if not recently_seeded:
                    expression_orchestrator.on_expression_change(expression_text)
            else:
                expression_orchestrator.on_expression_change("")

        cleanup_paths: list[str] = []
        if isinstance(payload, dict):
            cleanup_paths = self._collect_wav_paths(payload)
            playlist = self._extract_wav_playlist(payload)
            if len(playlist) >= 2:
                try:
                    self._play_audio_segments_with_lipsync(playlist, cleanup_paths=cleanup_paths)
                    logger.info(f"[LipSync] 启动分片无缝播放: segments={len(playlist)}")
                    return
                except Exception as exc:
                    logger.warning(f"[LipSync] 分片无缝播放失败，回退单wav: {exc}")

        if wav_path:
            wav_file = Path(wav_path)
            if wav_file.exists():
                paths_to_delete = cleanup_paths or [str(wav_file.resolve())]
                try:
                    self._play_audio_with_lipsync(str(wav_file), cleanup_paths=paths_to_delete)
                    logger.info(f"[LipSync] Python音频+嘴型启动: {wav_file.name}")
                    return
                except Exception as exc:
                    logger.warning(f"[LipSync] 音频驱动失败，尝试系统/浏览器回退: {exc}")
                    if self._play_with_platform_fallback(str(wav_file)):
                        self._cleanup_played_wavs(paths_to_delete, self._play_generation)
                        return
            else:
                logger.warning(f"[LipSync] 收到的wav文件不存在: {wav_file}")

        if not text:
            return

        try:
            self._lip_sync_manager.sync_with_text(text, duration_per_char=0.2, blocking=False)
            logger.warning(f"[LipSync] 已降级为文本驱动 (tts_status={tts_status or 'unknown'})")
        except Exception as exc:
            logger.warning(f"[LipSync] 文本驱动失败: {exc}")

    @staticmethod
    def _collect_wav_paths(payload: dict[str, Any]) -> list[str]:
        """收集 payload 中所有 wav 路径（去重、仅保留存在的文件）。"""
        ordered: list[str] = []
        seen: set[str] = set()

        def _add(path: str) -> None:
            normalized = str(Path(path).resolve())
            if normalized in seen:
                return
            if not Path(normalized).is_file():
                return
            seen.add(normalized)
            ordered.append(normalized)

        top = str(payload.get("wav_path") or "").strip()
        if top:
            _add(top)

        segments = payload.get("segments")
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                seg_path = str(segment.get("wav_path") or "").strip()
                if seg_path:
                    _add(seg_path)
        return ordered

    @staticmethod
    def _delete_wav_file(
        wav_path: str,
        *,
        retries: int = AUDIO_WAV_DELETE_RETRIES,
        delay_sec: float = AUDIO_WAV_DELETE_RETRY_DELAY_SEC,
    ) -> bool:
        target = Path(wav_path)
        if not target.is_file():
            return False
        for attempt in range(max(1, retries)):
            try:
                target.unlink(missing_ok=True)
                if not target.exists():
                    return True
            except PermissionError:
                time.sleep(delay_sec * (attempt + 1))
            except OSError as exc:
                logger.debug("[LipSync] 删除 wav 失败: %s (%s)", wav_path, exc)
                time.sleep(delay_sec * (attempt + 1))
        if target.exists():
            logger.warning("[LipSync] 删除 wav 仍失败（可能被占用）: %s", target.name)
        return not target.exists()

    def _cleanup_played_wavs(self, wav_paths: list[str], generation: int) -> None:
        if not self._delete_wav_after_playback or not wav_paths:
            return

        paths = list(dict.fromkeys(str(Path(p).resolve()) for p in wav_paths if p))

        def _deferred_cleanup() -> None:
            # 等待 PyAudio 流完全关闭、wave 模块释放文件句柄
            time.sleep(0.5)
            if self._is_playback_cancelled(generation):
                return
            deleted = 0
            failed: list[str] = []
            for wav_path in paths:
                if self._delete_wav_file(wav_path):
                    deleted += 1
                elif Path(wav_path).exists():
                    failed.append(Path(wav_path).name)
            if deleted:
                logger.info("[LipSync] 播放结束已删除 %s 个 TTS 临时文件", deleted)
            if failed:
                logger.warning("[LipSync] 未能删除: %s", ", ".join(failed))

        threading.Thread(
            target=_deferred_cleanup,
            daemon=True,
            name="audio-wav-cleanup",
        ).start()

    def warmup_audio_output(self) -> None:
        """启动后预热音频输出设备，减轻首句 TTS 开头被吞。"""

        def _worker() -> None:
            if self._audio_output_warmed:
                return
            pa = None
            stream = None
            try:
                import pyaudio

                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(2),
                    channels=1,
                    rate=32000,
                    output=True,
                    frames_per_buffer=AUDIO_FRAMES_PER_BUFFER,
                )
                silence = self._make_pcm16_silence(32000, 1, AUDIO_WARMUP_SILENCE_MS)
                stream.write(silence)
                stream.write(silence)
                self._audio_output_warmed = True
                logger.info("[LipSync] 音频输出设备预热完成")
            except Exception as exc:
                logger.debug("[LipSync] 音频预热跳过: %s", exc)
            finally:
                self._cleanup_output_stream(pa, stream)

        threading.Thread(target=_worker, daemon=True, name="audio-output-warmup").start()

    def _try_browser_audio(self, wav_path: str) -> bool:
        avatar = self._avatar_widget
        if avatar is None or not hasattr(avatar, "play_audio"):
            return False
        try:
            avatar.play_audio(wav_path)
            logger.info("[LipSync] 已通过 Viewer 浏览器播放: %s", Path(wav_path).name)
            return True
        except Exception as exc:
            logger.warning("[LipSync] Viewer 音频播放失败: %s", exc)
            return False

    def _play_winsound_blocking(self, wav_path: str, generation: int) -> bool:
        if os.name != "nt":
            return False
        try:
            import winsound

            lipsync_thread = threading.Thread(
                target=self._drive_lipsync_from_wav_file,
                args=(wav_path, generation),
                daemon=True,
                name="audio-lipsync-winsound",
            )
            lipsync_thread.start()
            winsound.PlaySound(wav_path, winsound.SND_FILENAME)
            return not self._is_playback_cancelled(generation)
        except Exception as exc:
            logger.warning("[LipSync] winsound 播放失败: %s", exc)
            return False

    def _play_with_platform_fallback(self, wav_path: str) -> bool:
        """PyAudio 失败时用 Windows winsound 或 Viewer 出声。"""
        generation = self._play_generation
        if self._play_winsound_blocking(wav_path, generation):
            manager = self._lip_sync_manager
            if manager is not None:
                manager._player._callback(0.0)
            return True
        return self._try_browser_audio(wav_path)

    def _drive_lipsync_from_wav_file(self, wav_path: str, generation: int) -> None:
        manager = self._lip_sync_manager
        if manager is None:
            return
        import struct
        import wave as _wave

        try:
            with _wave.open(wav_path, "rb") as wf:
                sampwidth = int(wf.getsampwidth() or 2)
                channels = int(wf.getnchannels() or 1)
                framerate = max(1, int(wf.getframerate() or 32000))
                chunk_frames = AUDIO_FRAMES_PER_BUFFER
                update_counter = 0
                while not self._is_playback_cancelled(generation):
                    data = wf.readframes(chunk_frames)
                    if not data:
                        break
                    if sampwidth == 2:
                        update_counter += 1
                        if update_counter % AUDIO_LIPSYNC_UPDATE_INTERVAL == 0:
                            samples = struct.unpack(f"<{len(data) // 2}h", data)
                            volume = self._compute_lipsync_volume_from_pcm16(samples)
                            manager._player._callback(volume)
                    frame_count = len(data) // max(1, sampwidth * channels)
                    time.sleep(frame_count / framerate)
        except Exception:
            logger.exception("[LipSync] winsound 嘴型驱动失败 path=%s", wav_path)
        finally:
            if not self._is_playback_cancelled(generation):
                manager._player._callback(0.0)

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
    def _make_pcm16_silence(sample_rate: int, channels: int, duration_ms: int) -> bytes:
        frame_count = max(1, int(sample_rate * max(1, duration_ms) / 1000))
        sample_count = frame_count * max(1, channels)
        return b"\x00\x00" * sample_count

    def _open_output_stream(
        self,
        pa: Any,
        stream: Any,
        sampwidth: int,
        channels: int,
        framerate: int,
    ) -> tuple[Any, Any]:
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
        if sampwidth == 2:
            prebuffer_ms = AUDIO_PREBUFFER_MS
            if self._needs_first_play_prebuffer:
                prebuffer_ms = max(prebuffer_ms, AUDIO_FIRST_PLAY_PREBUFFER_MS)
                self._needs_first_play_prebuffer = False
            if prebuffer_ms > 0:
                stream.write(self._make_pcm16_silence(framerate, channels, prebuffer_ms))
        return pa, stream

    @staticmethod
    def _cleanup_output_stream(pa: Any, stream: Any) -> None:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    def _stream_segment_and_drive_lipsync(
        self,
        stream: Any,
        raw_data: bytes,
        sampwidth: int,
        channels: int,
        generation: int,
    ) -> None:
        if not raw_data:
            return

        manager = self._lip_sync_manager
        import struct

        chunk_size = max(2, AUDIO_FRAMES_PER_BUFFER * max(1, sampwidth) * max(1, channels))
        update_counter = 0
        for offset in range(0, len(raw_data), chunk_size):
            if self._is_playback_cancelled(generation):
                return
            chunk = raw_data[offset : offset + chunk_size]
            if not chunk:
                continue
            stream.write(chunk)
            if manager is None or sampwidth != 2:
                continue
            update_counter += 1
            if update_counter % AUDIO_LIPSYNC_UPDATE_INTERVAL != 0:
                continue
            fmt = f"<{len(chunk) // 2}h"
            samples = struct.unpack(fmt, chunk)
            volume = self._compute_lipsync_volume_from_pcm16(samples)
            manager._player._callback(volume)

    def _play_audio_segments_with_lipsync(
        self,
        wav_paths: list[str],
        *,
        cleanup_paths: Optional[list[str]] = None,
    ) -> None:
        """Play multiple wav files on one output stream to reduce gaps/clicks."""
        if not self._lip_sync_manager or not wav_paths:
            return

        import wave as _wave

        delete_paths = cleanup_paths or [str(Path(p).resolve()) for p in wav_paths]

        def _worker(generation: int) -> None:
            manager = self._lip_sync_manager
            if manager is None or self._is_playback_cancelled(generation):
                return

            # 预加载所有分片数据到内存，避免播放期间的 I/O 开销
            segments: list[tuple[bytes, int, int, int]] = []  # (raw_data, sampwidth, channels, framerate)
            try:
                for wav_path in wav_paths:
                    if self._is_playback_cancelled(generation):
                        return
                    with _wave.open(wav_path, "rb") as wf:
                        n_channels = int(wf.getnchannels() or 1)
                        sampwidth = int(wf.getsampwidth() or 2)
                        framerate = int(wf.getframerate() or 32000)
                        raw_data = wf.readframes(int(wf.getnframes() or 0))
                        segments.append((raw_data, sampwidth, n_channels, framerate))
            except Exception:
                logger.exception("[LipSync] 预加载 WAV 失败")
                if wav_paths:
                    self._play_with_platform_fallback(wav_paths[0])
                return

            if not segments or self._is_playback_cancelled(generation):
                return

            # 淡出处理（仅非末尾分片）
            total = len(segments)
            processed: list[bytes] = []
            for idx, (raw_data, sampwidth, n_channels, framerate) in enumerate(segments):
                if sampwidth == 2 and raw_data:
                    raw_data = self._apply_edge_fade_pcm16(
                        raw_data,
                        channels=n_channels,
                        sample_rate=framerate,
                        fade_ms=AUDIO_SEGMENT_FADE_MS,
                        fade_in=False,
                        fade_out=(idx < total - 1),
                    )
                processed.append(raw_data)

            # 拼接为单一缓冲区，一次性写入流
            first = segments[0]
            n_channels, sampwidth, framerate = first[2], first[1], first[3]
            combined = b"".join(processed)

            pa = None
            stream = None
            try:
                pa, stream = self._open_output_stream(pa, stream, sampwidth, n_channels, framerate)
                self._stream_segment_and_drive_lipsync(
                    stream, combined, sampwidth, n_channels, generation,
                )
            except Exception:
                logger.exception("[LipSync] 拼接播放失败")
                if wav_paths:
                    self._play_with_platform_fallback(wav_paths[0])
            finally:
                # 先关闭流，等待 PyAudio 缓冲区排空
                self._cleanup_output_stream(pa, stream)
                # 流关闭后再重置嘴型，避免音频还在播放但嘴型已停
                if not self._is_playback_cancelled(generation):
                    manager._player._callback(0.0)
                self._cleanup_played_wavs(delete_paths, generation)

        self._start_playback_worker(_worker)

    def _play_audio_with_lipsync(
        self,
        wav_path: str,
        *,
        cleanup_paths: Optional[list[str]] = None,
    ) -> None:
        """Python 端 pyaudio 播放 + LipSyncManager 驱动嘴型（纯本地方案）。"""
        if not self._lip_sync_manager:
            return

        import wave as _wave

        delete_paths = cleanup_paths or [str(Path(wav_path).resolve())]

        def _worker(generation: int) -> None:
            manager = self._lip_sync_manager
            if manager is None or self._is_playback_cancelled(generation):
                return

            pa = None
            stream = None
            played = False
            try:
                with _wave.open(wav_path, "rb") as wf:
                    n_channels = int(wf.getnchannels() or 1)
                    sampwidth = int(wf.getsampwidth() or 2)
                    framerate = int(wf.getframerate() or 32000)
                    pa, stream = self._open_output_stream(None, None, sampwidth, n_channels, framerate)

                    update_counter = 0
                    data = wf.readframes(AUDIO_FRAMES_PER_BUFFER)
                    while data and not self._is_playback_cancelled(generation):
                        stream.write(data)
                        played = True
                        update_counter += 1
                        if update_counter % AUDIO_LIPSYNC_UPDATE_INTERVAL == 0 and sampwidth == 2:
                            import struct

                            fmt = f"<{len(data) // 2}h"
                            samples = struct.unpack(fmt, data)
                            volume = self._compute_lipsync_volume_from_pcm16(samples)
                            manager._player._callback(volume)
                        data = wf.readframes(AUDIO_FRAMES_PER_BUFFER)
            except Exception:
                logger.exception("[LipSync] 单文件播放失败 path=%s", wav_path)
                if not played:
                    self._play_with_platform_fallback(wav_path)
            finally:
                # 先关闭流，等待 PyAudio 缓冲区排空
                self._cleanup_output_stream(pa, stream)
                # 流关闭后再重置嘴型，避免音频还在播放但嘴型已停
                if not self._is_playback_cancelled(generation):
                    manager._player._callback(0.0)
                self._cleanup_played_wavs(delete_paths, generation)

        self._start_playback_worker(_worker)

    def cleanup(self):
        self._play_generation += 1
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0
