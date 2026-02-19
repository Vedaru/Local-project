"""window — 窗口管理辅助函数（从 ActionExecutor 拆分）

导出：capture_window_titles(), maximize_new_windows()
"""
from typing import Optional


def capture_window_titles() -> set:
    """返回当前可见窗口标题集合（用于比较新打开的窗口）。"""
    try:
        import pygetwindow as gw
        return set([w.title for w in gw.getAllWindows() if w.title and w.title.strip()])
    except Exception:
        return set()


def maximize_new_windows(before_titles: set, title_hint: Optional[str] = None, timeout: float = 3.0) -> int:
    """查找在 before_titles 之后新出现的窗口并尝试最大化。返回最大化窗口数量。"""
    try:
        import time
        import pygetwindow as gw
        end = time.time() + timeout
        maximized = 0
        while time.time() < end:
            all_windows = [w for w in gw.getAllWindows() if w.title and w.title.strip()]
            new_windows = [w for w in all_windows if w.title not in before_titles]
            if title_hint:
                new_windows = [w for w in new_windows if title_hint.lower() in w.title.lower()]
            if new_windows:
                for w in new_windows:
                    try:
                        w.maximize()
                        maximized += 1
                    except Exception:
                        pass
                break
            time.sleep(0.2)
        return maximized
    except Exception:
        # 回退：尝试使用快捷键最大化当前活动窗口
        try:
            import pyautogui
            pyautogui.hotkey('win', 'up')
            return 1
        except Exception:
            return 0