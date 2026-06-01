"""
Project Local - Entry Point

Minimal entry point responsible for:
1. Loading centralized configuration (AppConfig)
2. Creating QApplication
3. Integrating asyncio event loop with Qt via qasync
4. Starting LocalProjectApplication (Avatar GUI with microservices client)
"""

import atexit
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
from modules.config import get_cached_config
from modules.logging_config import get_logger
from modules.python_runtime_guard import ensure_supported_python_runtime


def main() -> None:
    """Main entry: bridge asyncio and Qt event loops via qasync."""
    logger = get_logger("ProjectLocal")
    logger.info("启动 Project Local...")
    ensure_supported_python_runtime(logger=logger)

    quit_event: Optional[asyncio.Event] = None

    app_config = get_cached_config()

    from modules.startup_self_check import (
        load_startup_check_options,
        log_startup_report,
        run_startup_self_check,
        should_abort_startup,
    )

    startup_opts = load_startup_check_options()
    if startup_opts.enabled:
        logger.info("正在执行开机自检...")
        startup_report = run_startup_self_check(app_config, options=startup_opts)
        log_startup_report(logger, startup_report)
        if should_abort_startup(startup_report, options=startup_opts):
            logger.error(
                "开机自检未通过（严格模式）：请运行 scripts\\install.bat 安装依赖、"
                "scripts\\start.bat 启动微服务，修复日志中的 [FAIL] 项。"
                "仅调试时可设 SKIP_STARTUP_SELF_CHECK=1 或 startup.strict_mode: false。"
            )
            input("\n按 Enter 键退出...")
            sys.exit(1)

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
        logger.error("qasync 未安装。请运行: pip install qasync\n" "qasync 用于将 asyncio 事件循环与 PyQt6 事件循环集成，" "是当前架构的必要依赖。")
        sys.exit(1)

    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    from application import LocalProjectApplication

    gui_app = LocalProjectApplication(app_config, qt_app)
    gui_app.setup()

    # atexit 兜底：确保子进程在任何退出路径下都被清理
    atexit.register(gui_app.cleanup)

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
