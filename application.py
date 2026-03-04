"""
LocalProjectApplication — GUI 层

封装所有 PyQt6 GUI 逻辑（窗口、Widget、信号/槽），并提供与
AICoreService 交互的接口。

职责:
  - 创建和管理 QApplication
  - Avatar 窗口（AvatarWidget）及 LipSync / ExpressionManager
  - 将用户输入（控制台 / 麦克风）提交给 AICoreService
  - 接收 AICoreService 的回调并更新 GUI
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import wave
from contextlib import suppress
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core_service import AICoreService, ServiceCallbacks
from modules.agent.core import ManusAgent
from modules.avatar import AvatarWidget, Emotion, ExpressionManager, LipSyncManager
from modules.avatar.logger import log_info as avatar_log_info
from modules.config import AppConfig
from modules.logging_config import get_logger
from modules.memory import MemoryManager
from modules.utils import filter_emotion_tags, start_gpt_sovits_api
from modules.voice import VoiceManager

logger = get_logger("Application")


# ---- Qt 信号桥接 ----


class _GUISignals(QObject):
    """跨线程信号 — 由 AICoreService 的回调触发，在 Qt 主线程执行槽函数。"""

    response_ready = pyqtSignal(str)
    lip_sync_update = pyqtSignal(float)
    expression_change = pyqtSignal(object)
    motion_play = pyqtSignal(str, int)
    status_update = pyqtSignal(str)
    shutdown = pyqtSignal()
    speak_request = pyqtSignal(str)
    play_audio = pyqtSignal(str)
    ear_recognized = pyqtSignal(str)


# ---- Ear Worker ----


class _EarWorker(threading.Thread):
    """后台线程：监听麦克风 → 识别文本 → 提交给 AICoreService。"""

    def __init__(self, core_service: AICoreService, model_size: str = "base"):
        super().__init__(daemon=True)
        self.core_service = core_service
        self.model_size = model_size
        self.ear = None  # type: ignore
        self._running = True

    def run(self):
        ear_logger = get_logger("Ear")
        try:
            # Lazy import — Ear pulls in faster_whisper/ctranslate2 which needs
            # the DLL patch applied first (done in main.py before we get here).
            from modules.ear import Ear

            ear_logger.info(f"🎙️  初始化听觉模块，模型大小: {self.model_size}")
            self.ear = Ear(model_size=self.model_size)

            def on_text(text: str):
                if self._running and text.strip():
                    ear_logger.info(f"🎯 识别结果: {text}")
                    self.core_service.submit(text)

            self.ear.listen(callback=on_text)
        except Exception as e:
            ear_logger.error(f"❌ 错误: {e}", exc_info=True)
        finally:
            if self.ear:
                self.ear.close()
            ear_logger.info("🛑 听觉模块已关闭")

    def stop(self):
        self._running = False
        if self.ear:
            self.ear.stop()


# ---- 主应用类 ----


class LocalProjectApplication:
    """GUI 应用 — 管理 QApplication、Avatar、信号连接和组件生命周期。

    Parameters
    ----------
    app_config : AppConfig
        集中配置对象。
    qt_app : QApplication
        已由 main.py 创建的 QApplication 实例。
    """

    def __init__(self, app_config: AppConfig, qt_app: QApplication):
        self.config = app_config
        self.app = qt_app

        # 组件引用（setup 后填充）
        self.avatar: Optional[AvatarWidget] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.voice_manager: Optional[VoiceManager] = None
        self.agent: Optional[ManusAgent] = None
        self.core_service: Optional[AICoreService] = None
        self.ear_worker: Optional[_EarWorker] = None

        self.lip_sync_manager: Optional[LipSyncManager] = None
        self.expression_manager: Optional[ExpressionManager] = None

        self.sovits_process = None

        # Qt 信号
        self._signals = _GUISignals()

        # 控制台输入
        self._can_input = threading.Event()
        self._can_input.set()

    # ==================== 初始化 ====================

    def setup(self):
        """同步初始化所有组件（在 Qt 事件循环启动前调用）。"""
        self._connect_signals()

        # GPT-SoVITS 服务
        self.sovits_process = start_gpt_sovits_api(self.config.gpt_sovits_path)
        if self.sovits_process is None:
            logger.warning("GPT-SoVITS API 服务启动失败。")

        # 初始化模块
        self.memory_manager = MemoryManager()
        self.voice_manager = VoiceManager(
            sovits_url=self.config.sovits_url,
            ref_audio=self.config.ref_audio,
            prompt_text=self.config.prompt_text,
        )

        # Agent
        self.agent = ManusAgent(
            system_prompt=self.config.system_prompt or "",
            max_steps=self.config.agent_max_steps,
        )
        logger.info("OpenManus 智能体已初始化")

        # 清理旧记忆
        self.memory_manager.cleanup_old_memories()

        # Avatar
        self.avatar = AvatarWidget(
            width=self.config.avatar_width,
            height=self.config.avatar_height,
            x=self.config.avatar_x,
            y=self.config.avatar_y,
        )

        # LipSync & Expression
        self.lip_sync_manager = LipSyncManager(update_callback=lambda v: self._signals.lip_sync_update.emit(v))
        self.expression_manager = ExpressionManager(
            expression_callback=self._change_expression,
            motion_callback=self._play_motion,
        )

        # Core Service（异步 AI 核心）
        callbacks = ServiceCallbacks(
            on_response_ready=self._signals.response_ready.emit,
            on_expression_change=self._signals.expression_change.emit,
            on_status_update=self._signals.status_update.emit,
            on_speak_request=self._signals.speak_request.emit,
            on_shutdown=self._signals.shutdown.emit,
        )
        self.core_service = AICoreService(
            config=self.config,
            memory_manager=self.memory_manager,
            voice_manager=self.voice_manager,
            agent=self.agent,
            callbacks=callbacks,
        )

    # ==================== 运行 ====================

    def show_and_start(self):
        """显示窗口、启动后台任务（在 asyncio 事件循环已启动后调用）。"""
        self.avatar.show()
        QTimer.singleShot(1500, self._load_default_model)

        # Ear - 仅当启用时启动
        if self.config.ear_enabled:
            logger.info("🎤 正在启动 Ear 听觉模块...")
            self.ear_worker = _EarWorker(self.core_service, model_size=self.config.ear_model_size)
            self.ear_worker.start()
        else:
            logger.info("⏭️  听觉模块已禁用")

        # Core Service（后台 asyncio Task）
        self.core_service.start_background()

        # 启动信息
        self.memory_manager.get_memory_stats()
        logger.info("🤖  Project Local 已启动（带 Avatar 模块）")
        if self.config.ear_enabled:
            logger.info("💬  现在可以直接输入文字进行对话，或通过麦克风说话！")
        else:
            logger.info("💬  现在可以直接输入文字进行对话！")
        logger.info("输入 'exit' 或 'quit' 退出，输入 'status' 查看记忆状态。")

        # 控制台输入线程
        console_thread = threading.Thread(target=self._console_input_loop, daemon=True)
        console_thread.start()

    # ==================== 信号连接 ====================

    def _connect_signals(self):
        s = self._signals
        s.response_ready.connect(self._on_response_ready)
        s.lip_sync_update.connect(self._on_lip_sync_update)
        s.expression_change.connect(self._on_expression_change)
        s.motion_play.connect(self._on_motion_play)
        s.status_update.connect(self._on_status_update)
        s.shutdown.connect(self._on_shutdown)
        s.speak_request.connect(self._on_speak_request)
        s.play_audio.connect(self._on_play_audio)
        s.ear_recognized.connect(self._on_ear_recognized)

    # ==================== 槽函数 ====================

    def _change_expression(self, expression_index: int):
        if self.avatar:
            self.avatar.change_expression(expression_index)

    def _play_motion(self, group: str, index: int):
        if self.avatar:
            self.avatar.play_motion(group, index)

    def _on_response_ready(self, response: str):
        logger.info(f"AI: {response}")
        self._can_input.set()

    def _on_lip_sync_update(self, value: float):
        if self.avatar:
            self.avatar.update_lip_sync(value)

    def _on_expression_change(self, expression):
        if self.expression_manager:
            if isinstance(expression, Emotion):
                self.expression_manager.set_emotion(expression)
            elif isinstance(expression, str):
                self.expression_manager.set_expression_from_text(expression)

    def _on_motion_play(self, group: str, index: int):
        if self.avatar:
            self.avatar.play_motion(group, index)

    def _on_status_update(self, status: str):
        logger.info(f"📊 {status}")

    def _on_speak_request(self, text: str):
        """语音合成 + 浏览器播放 + 口型同步。"""
        speak_text = text
        try:
            m = re.search(r"(\{(?:.|\n)*?\})", text)
            if m:
                try:
                    candidate = json.loads(m.group(1))
                    if isinstance(candidate, dict) and "thought" in candidate and isinstance(candidate["thought"], str):
                        speak_text = candidate["thought"]
                except Exception:
                    pass
        except Exception:
            pass

        filtered_text = filter_emotion_tags(speak_text)
        logger.debug(f"[TTS] 收到语音请求(用于朗读): {filtered_text[:50]}...")

        if self.voice_manager and self.avatar:
            try:
                wav_path = os.path.join(self.config.project_root, "data", "temp", f"tts_{int(time.time() * 1000)}.wav")
                os.makedirs(os.path.dirname(wav_path), exist_ok=True)

                def speak_with_browser():
                    try:
                        if not self.voice_manager.speak_and_save(filtered_text, wav_path):
                            logger.warning("[TTS] 语音合成失败")
                            return

                        self._signals.play_audio.emit(wav_path)

                        try:
                            with wave.open(wav_path, "rb") as wf:
                                duration = wf.getnframes() / float(wf.getframerate())
                            time.sleep(duration + 0.5)
                            with suppress(Exception):
                                os.remove(wav_path)
                        except Exception as e:
                            logger.warning(f"[TTS] 读取 wav 错误: {e}")
                    except Exception as e:
                        logger.error(f"[TTS] 错误: {e}", exc_info=True)

                threading.Thread(target=speak_with_browser, daemon=True).start()
            except Exception as e:
                logger.error(f"[TTS] 错误: {e}", exc_info=True)

    def _on_play_audio(self, wav_path: str):
        if self.avatar:
            self.avatar.play_audio(wav_path)

    def _on_ear_recognized(self, text: str):
        logger.info(f"👂 Ear 识别: {text}")

    def _on_shutdown(self):
        self.cleanup()
        self.app.quit()

    # ==================== 模型加载 ====================

    def _load_default_model(self):
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

    # ==================== 控制台输入 ====================

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

    # ==================== 清理 ====================

    def cleanup(self):
        """同步清理所有资源。"""
        if self.lip_sync_manager:
            self.lip_sync_manager.stop()

        if self.ear_worker:
            self.ear_worker.stop()

        # 停止 core_service（通过提交 None）
        if self.core_service:
            self.core_service.submit(None)

        if self.memory_manager:
            self.memory_manager.summarize_day()
            self.memory_manager.close()

        if self.agent:
            self.agent.cleanup()

        if self.sovits_process:
            self.sovits_process.terminate()
            self.sovits_process.wait()
            logger.info("GPT-SoVITS API 服务已停止。")
