"""
LocalProjectApplication - GUI layer

Encapsulates PyQt6 GUI logic and integrates with microservice client.
Refactored: delegates to ExpressionOrchestrator, AudioPlaybackController, ConsoleInputManager.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional, cast

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from microservices.service_client import MicroserviceAIService, ServiceCallbacks, create_ai_service
from modules.application.audio_playback_controller import AudioPlaybackController
from modules.application.console_input_manager import ConsoleInputManager
from modules.application.expression_orchestrator import ExpressionOrchestrator
from modules.avatar import AvatarWidget, ExpressionManager, LipSyncManager
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


class _EarWorker(threading.Thread):  # type: ignore[name-defined]
    """Background worker: microphone -> speech recognition -> submit to service."""

    def __init__(self, core_service: MicroserviceAIService, model_size: str = "base"):
        super().__init__(daemon=True)
        self.core_service = core_service
        self.model_size = model_size
        self.ear: Any = None
        self._running = True

    def run(self):
        ear_logger = get_logger("Ear")
        try:
            from modules.ear import Ear

            ear_logger.info(f"初始化听觉模块，模型大小: {self.model_size}")
            ear = Ear(model_size=self.model_size)
            self.ear = ear

            def on_text(text: str):
                if self._running and text.strip():
                    ear_logger.info(f"识别结果: {text}")
                    self.core_service.submit(text)

            ear.listen(callback=on_text)
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
    """GUI application orchestrator for avatar and microservice client.

    Responsibilities (after refactoring):
    - Component lifecycle management (create/wire/start/cleanup)
    - Signal routing between components and GUI signals
    - Avatar widget setup and model loading
    """

    def __init__(self, app_config: AppConfig, qt_app: QApplication):
        self.config = app_config
        self.app = qt_app

        # Core components
        self.avatar: Optional[AvatarWidget] = None
        self.core_service: Optional[MicroserviceAIService] = None
        self.ear_worker: Optional[_EarWorker] = None

        # Sub-controllers (extracted from god class)
        self._expression_orchestrator: Optional[ExpressionOrchestrator] = None
        self._audio_controller: Optional[AudioPlaybackController] = None
        self._console_manager: Optional[ConsoleInputManager] = None

        # Avatar sub-managers
        self.lip_sync_manager: Optional[LipSyncManager] = None
        self.expression_manager: Optional[ExpressionManager] = None

        # Internal state
        self._signals = _GUISignals()
        self._cleaned_up = False

    def setup(self):
        self._connect_signals()
        self._init_backend_components()
        self._init_core_service()
        self._init_avatar_components()

    def _init_backend_components(self):
        logger.info("后端运行模式: microservices-only")

    def _init_avatar_components(self):
        core_service = self.core_service
        assert core_service is not None
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

        # Create sub-controllers with extracted components
        self._expression_orchestrator = ExpressionOrchestrator(
            expression_manager=self.expression_manager,
            qt_app=self.app,
        )
        self._audio_controller = AudioPlaybackController(
            lip_sync_manager=self.lip_sync_manager,
        )
        self._console_manager = ConsoleInputManager(
            submit_fn=lambda text: core_service.submit(text),
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
        if self.avatar is None or self.core_service is None:
            raise RuntimeError("setup() did not initialize avatar or core service")
        self.avatar.show()
        QTimer = self.__import_qtimer()  # noqa: N806
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

        if self._console_manager:
            self._console_manager.start()

    @staticmethod
    def __import_qtimer():
        from PyQt6.QtCore import QTimer

        return QTimer

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
        if self._console_manager:
            self._console_manager.can_input.set()

    def _on_lip_sync_update(self, value: object):
        if self.avatar:
            self.avatar.update_lip_sync(cast(Any, value))

    def _on_expression_change(self, expression):
        if self._expression_orchestrator:
            self._expression_orchestrator.on_expression_change(expression)

    def _on_motion_play(self, group: str, index: int):
        if self.avatar:
            self.avatar.play_motion(group, index)

    def _on_status_update(self, status: str):
        logger.info(f"状态: {status}")

    def _on_ear_recognized(self, text: str):
        logger.info(f"Ear 识别: {text}")

    def _on_speak_request(self, payload: object) -> None:
        if self._audio_controller and self._expression_orchestrator:
            self._audio_controller.on_speak_request(
                payload,
                expression_orchestrator=self._expression_orchestrator,
            )

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

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True

        # Delegate cleanup to sub-controllers
        if self._expression_orchestrator:
            self._expression_orchestrator.cleanup()
        if self._audio_controller:
            self._audio_controller.cleanup()

        if self.lip_sync_manager:
            self.lip_sync_manager.stop()
            self.lip_sync_manager = None

        if self.ear_worker:
            self.ear_worker.stop()
            self.ear_worker = None

        if self.core_service:
            self.core_service.close()
            self.core_service = None
