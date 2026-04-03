"""
Project Local - Entry Point

Minimal entry point responsible for:
1. Loading centralized configuration (AppConfig)
2. Creating QApplication
3. Integrating asyncio event loop with Qt via qasync
4. Starting LocalProjectApplication (Avatar GUI with microservices client)
"""

import os
import signal
import sys
from typing import Optional

# Must be set before importing ctranslate2/faster_whisper related modules.
os.environ["CT2_USE_CUDA"] = "0"

# Avoid Windows wmic/encoding issues in loky when counting physical cores.
if "LOKY_MAX_CPU_COUNT" not in os.environ:
    os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 4)

import asyncio

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication

# Apply ctranslate2 DLL patch before modules that may import faster_whisper.
import modules._patch_ctranslate2  # noqa: F401, E402
from modules.config import load_config
from modules.logging_config import get_logger


def main() -> None:
    """Main entry: bridge asyncio and Qt event loops via qasync."""
    logger = get_logger("ProjectLocal")
    logger.info("启动 Project Local...")

    quit_event: Optional[asyncio.Event] = None

    app_config = load_config()

    # Required by QtWebEngine: set before QApplication is created.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    qt_app = QApplication(sys.argv)

    def _signal_handler(sig, frame):
        logger.info("收到中断信号，正在请求 Qt 主循环退出...")
        qt_app.quit()
        if quit_event is not None and not quit_event.is_set():
            quit_event.set()

    signal.signal(signal.SIGINT, _signal_handler)

    try:
        import qasync
    except ImportError:
        logger.error(
            "qasync 未安装。请运行: pip install qasync\n"
            "qasync 用于将 asyncio 事件循环与 PyQt6 事件循环集成，"
            "是当前架构的必要依赖。"
        )
        sys.exit(1)

    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    from application import LocalProjectApplication

    gui_app = LocalProjectApplication(app_config, qt_app)
    gui_app.setup()

    quit_event = asyncio.Event()

    def _on_about_to_quit():
        if not quit_event.is_set():
            quit_event.set()

    qt_app.aboutToQuit.connect(_on_about_to_quit)

    async def _run():
        gui_app.show_and_start()
        await quit_event.wait()

    try:
        with loop:
            loop.run_until_complete(_run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到中断信号，正在清理资源...")
    finally:
        gui_app.cleanup()

    sys.exit(0)


if __name__ == "__main__":
    main()
