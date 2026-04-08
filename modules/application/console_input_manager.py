"""
ConsoleInputManager — 控制台输入循环

从 LocalProjectApplication 中提取，负责:
- 控制台文本输入读取
- 输入节流（can_input Event）
- 退出命令检测
"""

import threading
from typing import Callable, Optional

from modules.logging_config import get_logger

logger = get_logger("ConsoleInputManager")


class ConsoleInputManager:
    """Manages console input loop with throttling."""

    EXIT_COMMANDS = {"exit", "quit"}

    def __init__(self, submit_fn: Callable[[str], None]):
        """
        Args:
            submit_fn: 回调函数，接收用户输入文本并提交给服务
        """
        self._submit_fn = submit_fn
        self._can_input = threading.Event()
        self._can_input.set()
        self._running = True

    @property
    def can_input(self) -> threading.Event:
        return self._can_input

    def start(self):
        """Start the console input loop in a daemon thread."""
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def _loop(self):
        import time

        time.sleep(0.5)
        while self._running:
            try:
                self._can_input.wait()
                user_input = input("")
                if user_input.strip():
                    self._can_input.clear()
                self._submit_fn(user_input)
                if user_input.strip().lower() in self.EXIT_COMMANDS:
                    self._running = False
                    break
            except EOFError:
                break
            except Exception:
                pass

    def stop(self):
        self._running = False
