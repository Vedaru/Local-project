"""
Avatar 模块 - 基于 PyQt6 + QWebEngineView 的 Live2D 模型显示

模块结构：
- widget.py: 主窗口部件
- manager.py: Avatar 管理器
- webengine.py: WebEngine 相关组件
- click_through.py: 点击穿透功能
- tray.py: 系统托盘
- resize.py: 窗口调整大小
- js_communication.py: JavaScript 通信
- logger.py: 日志系统
- lip_sync.py: 口型同步系统
- expression.py: 表情管理系统

使用方法：
    from modules.avatar import AvatarWidget, AvatarManager

    # 方式1: 直接使用 Widget
    widget = AvatarWidget(width=400, height=600, x=100, y=100)
    widget.show()
    widget.load_model("model/model.model3.json")

    # 方式2: 使用 Manager
    manager = AvatarManager()
    widget = manager.create_widget()
    manager.show()
    manager.load_model("model/model.model3.json")

    # 口型同步
    from modules.avatar import LipSyncManager
    lip_sync = LipSyncManager(callback=widget.set_mouth_open)
    lip_sync.sync_with_text("你好", duration=2.0)

    # 表情管理
    from modules.avatar import ExpressionManager, Emotion
    expr_mgr = ExpressionManager(expression_callback=widget.set_expression)
    expr_mgr.set_expression_from_text("太开心了！")
"""

from typing import TYPE_CHECKING, Any

from .expression import Emotion, EmotionAnalyzer, EmotionKeywords, ExpressionConfig, ExpressionManager
from .lip_sync import LipSyncAnalyzer, LipSyncFrame, LipSyncManager, LipSyncPlayer
from .logger import get_logger, log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from .manager import AvatarManager
    from .webengine import AvatarBridge, WebEnginePage
    from .widget import AvatarWidget


_GUI_SYMBOLS = {"AvatarWidget", "AvatarManager", "WebEnginePage", "AvatarBridge"}


def _load_gui_symbol(name: str) -> Any:
    try:
        if name == "AvatarWidget":
            from .widget import AvatarWidget as symbol
        elif name == "AvatarManager":
            from .manager import AvatarManager as symbol
        elif name == "WebEnginePage":
            from .webengine import WebEnginePage as symbol
        elif name == "AvatarBridge":
            from .webengine import AvatarBridge as symbol
        else:
            raise AttributeError(name)
    except Exception as exc:
        raise ImportError(
            "Avatar GUI features require PyQt6 and PyQt6-WebEngine to be installed."
        ) from exc

    globals()[name] = symbol
    return symbol


def __getattr__(name: str) -> Any:
    if name in _GUI_SYMBOLS:
        return _load_gui_symbol(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AvatarWidget",
    "AvatarManager",
    "WebEnginePage",
    "AvatarBridge",
    "get_logger",
    "log_info",
    "log_debug",
    "log_warning",
    "log_error",
    # Lip Sync
    "LipSyncManager",
    "LipSyncAnalyzer",
    "LipSyncPlayer",
    "LipSyncFrame",
    # Expression
    "ExpressionManager",
    "EmotionAnalyzer",
    "Emotion",
    "ExpressionConfig",
    "EmotionKeywords",
]

__version__ = "1.1.0"
