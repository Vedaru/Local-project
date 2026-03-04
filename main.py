"""
Project Local ---- Entry Point (Refactored)

Minimal entry point responsible for:
  1. Loading centralized configuration (AppConfig)
  2. Creating QApplication
  3. Integrating asyncio event loop with Qt via qasync
  4. Starting LocalProjectApplication (GUI) and AICoreService (AI backend)
"""

import os
import signal
import sys

# Must set before importing any other modules (fix ctranslate2 ROCm path issue)
os.environ["CT2_USE_CUDA"] = "0"

# Fix joblib/loky UnicodeDecodeError on Chinese Windows:
# loky tries to run `wmic` to count physical cores, which fails with GBK encoding.
# Setting LOKY_MAX_CPU_COUNT bypasses the wmic subprocess call entirely.
if "LOKY_MAX_CPU_COUNT" not in os.environ:
    os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 4)

# Apply ctranslate2 DLL patch before any module tries to import faster_whisper
import modules._patch_ctranslate2  # noqa: F401, E402

import asyncio

from PyQt6.QtWidgets import QApplication

from modules.config import load_config
from modules.logging_config import get_logger


def signal_handler(sig, frame):
    print("\n正在退出...")
    sys.exit(0)


def main():
    """Main entry -- integrate asyncio with PyQt6 via qasync."""
    logger = get_logger("ProjectLocal")
    logger.info("启动 Project Local...")

    signal.signal(signal.SIGINT, signal_handler)

    # Load centralized config
    app_config = load_config()

    # Create Qt application (must precede any Widget)
    qt_app = QApplication(sys.argv)

    # qasync bridges asyncio <-> Qt event loops
    try:
        import qasync
    except ImportError:
        logger.error(
            "qasync 未安装。请运行: pip install qasync\n"
            "qasync 用于将 asyncio 事件循环与 PyQt6 事件循环集成，"
            "是重构后架构的必要依赖。"
        )
        sys.exit(1)

    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    from application import LocalProjectApplication

    gui_app = LocalProjectApplication(app_config, qt_app)
    gui_app.setup()

    async def _run():
        gui_app.show_and_start()
        # qasync shares the event loop between asyncio and Qt;
        # we wait until Qt quits (which stops the loop).
        await asyncio.Event().wait()

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
