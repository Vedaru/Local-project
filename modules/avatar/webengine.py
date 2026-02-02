"""
WebEngine 相关组件 - 自定义 Page 和 Bridge
"""

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtWebEngineCore import QWebEnginePage

from .logger import log_js


class WebEnginePage(QWebEnginePage):
    """自定义 WebEnginePage，用于处理 JavaScript 控制台消息"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """捕获 JavaScript 控制台消息并记录到日志"""
        level_names = {0: 'INFO', 1: 'WARNING', 2: 'ERROR'}
        level_name = level_names.get(level, 'DEBUG')
        log_js(level_name, message, lineNumber)


class AvatarBridge(QObject):
    """
    用于 Python 和 JavaScript 之间双向通信的桥接类
    可通过 QWebChannel 暴露给 JavaScript
    """
    
    # 定义信号，用于从 JavaScript 通知 Python
    model_loaded = pyqtSignal(bool)
    model_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
