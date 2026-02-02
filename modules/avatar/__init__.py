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

from .widget import AvatarWidget
from .manager import AvatarManager
from .webengine import WebEnginePage, AvatarBridge
from .logger import get_logger, log_info, log_debug, log_warning, log_error
from .lip_sync import LipSyncManager, LipSyncAnalyzer, LipSyncPlayer, LipSyncFrame
from .expression import ExpressionManager, EmotionAnalyzer, Emotion, ExpressionConfig, EmotionKeywords

__all__ = [
    'AvatarWidget',
    'AvatarManager',
    'WebEnginePage',
    'AvatarBridge',
    'get_logger',
    'log_info',
    'log_debug',
    'log_warning',
    'log_error',
    # Lip Sync
    'LipSyncManager',
    'LipSyncAnalyzer',
    'LipSyncPlayer',
    'LipSyncFrame',
    # Expression
    'ExpressionManager',
    'EmotionAnalyzer',
    'Emotion',
    'ExpressionConfig',
    'EmotionKeywords',
]

__version__ = '1.1.0'
