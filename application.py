"""
LocalProjectApplication - GUI layer

Encapsulates PyQt6 GUI logic and integrates with microservice client.
"""

from __future__ import annotations

import threading
import time
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from microservices.service_client import ServiceCallbacks, create_ai_service
from modules.avatar import AvatarWidget, Emotion, ExpressionManager, LipSyncManager
from modules.avatar.logger import log_info as avatar_log_info
from modules.config import AppConfig
from modules.logging_config import get_logger
from modules.utils import sanitize_dialogue_text

logger = get_logger("Application")


class _GUISignals(QObject):
    """Cross-thread Qt signals for service callbacks."""

    response_ready = pyqtSignal(str)
    lip_sync_update = pyqtSignal(object)
    expression_change = pyqtSignal(object)
    motion_play = pyqtSignal(str, int)
    status_update = pyqtSignal(str)
    shutdown = pyqtSignal()
    ear_recognized = pyqtSignal(str)
    speak_request = pyqtSignal(object)  # TTS/嘴型触发（包含wav路径）


class _EarWorker(threading.Thread):
    """Background worker: microphone -> speech recognition -> submit to service."""

    def __init__(self, core_service, model_size: str = "base"):
        super().__init__(daemon=True)
        self.core_service = core_service
        self.model_size = model_size
        self.ear = None
        self._running = True

    def run(self):
        ear_logger = get_logger("Ear")
        try:
            from modules.ear import Ear

            ear_logger.info(f"初始化听觉模块，模型大小: {self.model_size}")
            self.ear = Ear(model_size=self.model_size)

            def on_text(text: str):
                if self._running and text.strip():
                    ear_logger.info(f"识别结果: {text}")
                    self.core_service.submit(text)

            self.ear.listen(callback=on_text)
        except Exception as e:
            ear_logger.error(f"听觉模块错误: {e}", exc_info=True)
        finally:
            if self.ear:
                self.ear.close()
            ear_logger.info("听觉模块已关闭")

    def stop(self):
        self._running = False
        if self.ear:
            self.ear.stop()


class LocalProjectApplication:
    """GUI application orchestrator for avatar and microservice client."""

    def __init__(self, app_config: AppConfig, qt_app: QApplication):
        self.config = app_config
        self.app = qt_app

        self.avatar: Optional[AvatarWidget] = None
        self.core_service = None
        self.ear_worker: Optional[_EarWorker] = None

        self.lip_sync_manager: Optional[LipSyncManager] = None
        self.expression_manager: Optional[ExpressionManager] = None

        self._signals = _GUISignals()
        self._can_input = threading.Event()
        self._can_input.set()
        self._cleaned_up = False
        self._expression_timers: list[QTimer] = []
        self._emotion_decay_timer: Optional[QTimer] = None
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0

    def setup(self):
        self._connect_signals()
        self._init_backend_components()
        self._init_avatar_components()
        self._init_core_service()

    def _init_backend_components(self):
        logger.info("后端运行模式: microservices-only")

    def _init_avatar_components(self):
        self.avatar = AvatarWidget(
            width=self.config.avatar_width,
            height=self.config.avatar_height,
            x=self.config.avatar_x,
            y=self.config.avatar_y,
        )

        self.lip_sync_manager = LipSyncManager(update_callback=lambda v: self._signals.lip_sync_update.emit(v))
        self.expression_manager = ExpressionManager(
            expression_callback=self._change_expression,
            motion_callback=self._play_motion,
        )

    def _init_core_service(self):
        callbacks = ServiceCallbacks(
            on_response_ready=self._signals.response_ready.emit,
            on_expression_change=self._signals.expression_change.emit,
            on_status_update=self._signals.status_update.emit,
            on_speak_request=self._signals.speak_request.emit,
            on_shutdown=self._signals.shutdown.emit,
        )
        self.core_service = create_ai_service(self.config, callbacks)

    def show_and_start(self):
        self.avatar.show()
        QTimer.singleShot(1500, self._load_default_model)

        if self.config.ear_enabled:
            logger.info("正在启动 Ear 听觉模块...")
            self.ear_worker = _EarWorker(self.core_service, model_size=self.config.ear_model_size)
            self.ear_worker.start()
        else:
            logger.info("听觉模块已禁用")

        self.core_service.start_background()

        logger.info("Project Local 已启动（microservices-only 模式）")
        logger.info("输入 'exit' 或 'quit' 退出，输入 'status' 查看微服务状态。")

        console_thread = threading.Thread(target=self._console_input_loop, daemon=True)
        console_thread.start()

    def _connect_signals(self):
        s = self._signals
        s.response_ready.connect(self._on_response_ready)
        s.lip_sync_update.connect(self._on_lip_sync_update)
        s.expression_change.connect(self._on_expression_change)
        s.motion_play.connect(self._on_motion_play)
        s.status_update.connect(self._on_status_update)
        s.speak_request.connect(self._on_speak_request)
        s.shutdown.connect(self._on_shutdown)
        s.ear_recognized.connect(self._on_ear_recognized)

    def _change_expression(self, expression_index: int):
        if self.avatar:
            self.avatar.change_expression(expression_index)

    def _play_motion(self, group: str, index: int):
        if self.avatar:
            self.avatar.play_motion(group, index)

    def _on_response_ready(self, response: str):
        natural_response = sanitize_dialogue_text(response)
        logger.info(f"AI: {natural_response or response}")
        self._can_input.set()

    def _on_lip_sync_update(self, value: object):
        if self.avatar:
            self.avatar.update_lip_sync(value)

    def _on_expression_change(self, expression):
        if not self.expression_manager:
            return

        if isinstance(expression, Emotion):
            self._clear_expression_timers()
            self.expression_manager.set_emotion(expression)
            if expression != Emotion.NEUTRAL:
                self._schedule_emotion_decay()
            return

        analyzable_text = ""

        if isinstance(expression, dict):
            analyzable_text = sanitize_dialogue_text(str(expression.get("text") or expression.get("answer") or ""))
        elif isinstance(expression, str):
            analyzable_text = sanitize_dialogue_text(expression)
        else:
            return

        if analyzable_text:
            self._pending_expression_text = analyzable_text
            self._start_weighted_expression_flow(analyzable_text, duration_sec=None)

    def _apply_expression_change(self, emotion: Emotion):
        if self.expression_manager:
            raw_play = (os.getenv("LOCAL_EXPRESSION_TIMELINE_PLAY_MOTION", "0") or "0").strip().lower()
            play_motion = raw_play in {"1", "true", "yes", "on"}
            self.expression_manager.set_emotion(emotion, play_motion=play_motion)

    def _clear_expression_timers(self):
        for timer in self._expression_timers:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass
        self._expression_timers.clear()

        if self._emotion_decay_timer is not None:
            try:
                self._emotion_decay_timer.stop()
                self._emotion_decay_timer.deleteLater()
            except Exception:
                pass
            self._emotion_decay_timer = None

    def _schedule_emotion_decay(self, delay_sec: Optional[float] = None) -> None:
        if not self.expression_manager:
            return

        current = self.expression_manager.current_emotion
        if current == Emotion.NEUTRAL:
            return

        if delay_sec is None:
            raw_delay = (os.getenv("LOCAL_EXPRESSION_AUTO_RESET_SEC", "2.4") or "2.4").strip()
            try:
                delay_sec = float(raw_delay)
            except ValueError:
                delay_sec = 2.4

        delay_sec = max(0.3, float(delay_sec))

        if self._emotion_decay_timer is not None:
            try:
                self._emotion_decay_timer.stop()
                self._emotion_decay_timer.deleteLater()
            except Exception:
                pass
            self._emotion_decay_timer = None

        target_emotion = current
        timer = QTimer(self.app)
        timer.setSingleShot(True)

        def _decay_to_neutral() -> None:
            if not self.expression_manager:
                return
            if self.expression_manager.current_emotion == target_emotion and target_emotion != Emotion.NEUTRAL:
                self.expression_manager.reset()
            if self._emotion_decay_timer is timer:
                self._emotion_decay_timer = None

        timer.timeout.connect(_decay_to_neutral)
        timer.start(int(delay_sec * 1000))
        self._emotion_decay_timer = timer

    def _start_weighted_expression_flow(self, text: str, duration_sec: Optional[float]) -> None:
        if not self.expression_manager:
            return

        cleaned = sanitize_dialogue_text(text)
        self._clear_expression_timers()
        if not cleaned:
            self.expression_manager.reset()
            return

        self._last_expression_seed_text = cleaned
        self._last_expression_seed_at = time.monotonic()

        timeline = self.expression_manager.build_weighted_timeline(cleaned, duration_sec=duration_sec)
        if not timeline:
            self.expression_manager.reset()
            return

        preview = ", ".join(f"{point.emotion.value}@{point.offset_sec:.2f}" for point in timeline[:8])
        logger.debug(f"[Expression] 时间线 points={len(timeline)} preview={preview}")

        raw_gap = (os.getenv("LOCAL_EXPRESSION_MIN_TIMER_GAP_MS", "120") or "120").strip()
        try:
            min_timer_gap_ms = int(raw_gap)
        except ValueError:
            min_timer_gap_ms = 120
        min_timer_gap_ms = max(40, min_timer_gap_ms)

        last_delay_ms = -min_timer_gap_ms

        for point in timeline:
            delay_ms = max(0, int(point.offset_sec * 1000))

            if delay_ms > 0 and delay_ms <= last_delay_ms:
                delay_ms = last_delay_ms + min_timer_gap_ms

            if delay_ms == 0 and last_delay_ms >= 0:
                delay_ms = last_delay_ms + min_timer_gap_ms

            if delay_ms == 0:
                self._apply_expression_change(point.emotion)
                last_delay_ms = 0
                continue

            timer = QTimer(self.app)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda emotion=point.emotion: self._apply_expression_change(emotion))
            timer.start(delay_ms)
            self._expression_timers.append(timer)
            last_delay_ms = delay_ms

    def _on_motion_play(self, group: str, index: int):
        if self.avatar:
            self.avatar.play_motion(group, index)

    def _on_status_update(self, status: str):
        logger.info(f"状态: {status}")

    def _on_ear_recognized(self, text: str):
        logger.info(f"Ear 识别: {text}")

    def _on_speak_request(self, payload: object) -> None:
        """TTS请求优先走真实音频驱动嘴型，缺失wav时再降级文本驱动。"""
        if not self.lip_sync_manager:
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

        if expression_text:
            recently_seeded = (
                expression_text == self._last_expression_seed_text and (now - self._last_expression_seed_at) < 1.2
            )
            if not recently_seeded:
                self._start_weighted_expression_flow(expression_text, duration_sec=duration_sec)

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

        if not text:
            return

        try:
            self.lip_sync_manager.sync_with_text(text, duration_per_char=0.2, blocking=False)
            logger.warning(f"[LipSync] 已降级为文本驱动 (tts_status={tts_status or 'unknown'})")
        except Exception as exc:
            logger.warning(f"[LipSync] 文本驱动失败: {exc}")

    def _play_audio_with_lipsync(self, wav_path: str) -> None:
        """Python 端 pyaudio 播放 + LipSyncManager 驱动嘴型（纯本地方案）。"""
        if not self.lip_sync_manager:
            return

        import wave as _wave
        import threading as _threading

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
                                self.lip_sync_manager._player._callback(volume)
                        data = wf.readframes(frames_per_buffer)

                    # 播放完成，闭嘴
                    self.lip_sync_manager._player._callback(0.0)
                    stream.stop_stream()
                    stream.close()
                    pa.terminate()
            except Exception:
                self.lip_sync_manager._player._callback(0.0)

        t = _threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_shutdown(self):
        self.cleanup()
        self.app.quit()

    def _load_default_model(self):
        if not self.avatar:
            return
        models_dir = Path(self.config.project_root) / "assets" / "web" / "models"
        if models_dir.exists():
            for model_file in models_dir.rglob("*.model3.json"):
                avatar_log_info(f"Found model: {model_file}")
                self.avatar.load_model(str(model_file))
                return
            for model_file in models_dir.rglob("*.model.json"):
                avatar_log_info(f"Found model: {model_file}")
                self.avatar.load_model(str(model_file))
                return
        avatar_log_info("No model found in models directory")

    def _console_input_loop(self):
        time.sleep(0.5)
        while True:
            try:
                self._can_input.wait()
                user_input = input("")
                if user_input.strip():
                    self._can_input.clear()
                self.core_service.submit(user_input)
                if user_input.lower() in ("exit", "quit"):
                    break
            except EOFError:
                break
            except Exception:
                pass

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True

        self._clear_expression_timers()
        self._pending_expression_text = ""
        self._last_expression_seed_text = ""
        self._last_expression_seed_at = 0.0

        if self.lip_sync_manager:
            self.lip_sync_manager.stop()
            self.lip_sync_manager = None

        if self.ear_worker:
            self.ear_worker.stop()
            self.ear_worker = None

        if self.core_service:
            self.core_service.close()
            self.core_service = None
