"""
Avatar 主窗口部件
"""

import sys
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSignal, QEvent, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtGui import QColor

from .logger import log_info, log_warning, log_error, log_debug
from .webengine import WebEnginePage, AvatarBridge
from .click_through import ClickThroughMixin
from .tray import TrayMixin
from .resize import ResizeMixin
from .js_communication import JSCommunicationMixin


class AvatarWidget(QMainWindow, ClickThroughMixin, TrayMixin, ResizeMixin, JSCommunicationMixin):
    """
    Live2D 虚拟形象显示窗口
    
    特性：
    - 无边框透明窗口
    - 总是置顶显示
    - 支持鼠标拖拽移动
    - 通过 JavaScript 控制 Live2D 模型
    """
    
    page_ready = pyqtSignal()
    
    def __init__(
        self,
        width: int = 400,
        height: int = 600,
        x: int = 100,
        y: int = 100,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        
        self._page_ready = False
        self._pending_model: Optional[str] = None
        self._pending_callback: Optional[Callable] = None
        
        # 保存初始窗口参数
        self._initial_width = width
        self._initial_height = height
        self._initial_x = x
        self._initial_y = y
        
        # 初始化调整大小状态
        self.init_resize_state()
        
        # 设置窗口属性
        self._setup_window(width, height, x, y)
        
        # 设置 WebEngine
        self._setup_webengine()
        
        # 设置系统托盘
        self.setup_tray()
        
        # 加载 HTML 页面
        self._load_viewer()
        
        log_info(f"AvatarWidget initialized ({width}x{height} at {x},{y})")
    
    def _setup_window(self, width: int, height: int, x: int, y: int):
        """配置窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(200, 200)
        self.setWindowTitle("Live2D Avatar")
        
        if sys.platform == 'win32':
            self._click_through_enabled = False
            self._click_through_setup_done = False
    
    def _setup_webengine(self):
        """配置 WebEngine 视图"""
        central_widget = QWidget(self)
        central_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.web_view = QWebEngineView()
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        self.web_page = WebEnginePage(self.web_view)
        self.web_view.setPage(self.web_page)
        self.web_page.setBackgroundColor(QColor(0, 0, 0, 0))
        
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        
        layout.addWidget(self.web_view)
        
        self.bridge = AvatarBridge(self)
        
        self.web_view.installEventFilter(self)
        self.web_view.setMouseTracking(True)
        
        QTimer.singleShot(100, self._install_child_event_filter)
        QTimer.singleShot(500, self._install_child_event_filter)
        QTimer.singleShot(1500, self._install_child_event_filter)
    
    def _install_child_event_filter(self):
        """为 WebEngineView 的子部件安装事件过滤器"""
        for child in self.web_view.findChildren(QWidget):
            child.installEventFilter(self)
            child.setMouseTracking(True)
        if self.web_view.focusProxy():
            self.web_view.focusProxy().installEventFilter(self)
            self.web_view.focusProxy().setMouseTracking(True)
        if self.centralWidget():
            self.centralWidget().setMouseTracking(True)
            self.centralWidget().installEventFilter(self)
    
    def _load_viewer(self):
        """加载 HTML 查看器页面"""
        current_dir = Path(__file__).parent.parent.parent
        viewer_path = current_dir / "assets" / "web" / "viewer.html"
        
        if not viewer_path.exists():
            log_error(f"viewer.html not found at {viewer_path}")
            return
        
        url = QUrl.fromLocalFile(str(viewer_path.resolve()))
        self.web_view.loadFinished.connect(self._on_page_load_finished)
        self.web_view.setUrl(url)
        
        log_info(f"Loading viewer from: {url.toString()}")
    
    def _on_page_load_finished(self, ok: bool):
        """页面加载完成回调"""
        if ok:
            log_debug("Page load finished, waiting for JS initialization...")
            self._check_js_ready()
        else:
            log_error("Page load failed!")
    
    def _check_js_ready(self):
        """检查 JavaScript 是否就绪"""
        def on_check_result(ready):
            if ready:
                log_info("JavaScript is ready!")
                self._page_ready = True
                self.page_ready.emit()
                if self._pending_model:
                    self._do_load_model(self._pending_model, self._pending_callback)
                    self._pending_model = None
                    self._pending_callback = None
            else:
                QTimer.singleShot(100, self._check_js_ready)
        
        self.run_js("typeof checkReady === 'function' && checkReady()", on_check_result)
    
    # ==================== 事件处理 ====================
    
    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        if sys.platform == 'win32' and hasattr(self, '_click_through_setup_done') and self._click_through_setup_done:
            QTimer.singleShot(100, self.apply_click_through)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        if sys.platform == 'win32':
            self.cleanup_global_hotkey()
        log_info("Window closing")
        super().closeEvent(event)
    
    def keyPressEvent(self, event):
        """键盘事件"""
        modifiers = event.modifiers()
        if (modifiers & Qt.KeyboardModifier.ControlModifier and 
            modifiers & Qt.KeyboardModifier.AltModifier and 
            event.key() == Qt.Key.Key_D):
            self.toggle_click_through()
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def mouseMoveEvent(self, event):
        """处理主窗口的鼠标移动事件"""
        if hasattr(self, '_click_through_enabled') and self._click_through_enabled:
            return super().mouseMoveEvent(event)
        
        global_pos = event.globalPosition().toPoint()
        local_pos = event.pos()
        
        if self.handle_mouse_move(global_pos, local_pos, event.buttons()):
            event.accept()
            return
        
        super().mouseMoveEvent(event)
    
    def mousePressEvent(self, event):
        """处理主窗口的鼠标按下事件"""
        if hasattr(self, '_click_through_enabled') and self._click_through_enabled:
            return super().mousePressEvent(event)
        
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            local_pos = event.pos()
            self.handle_mouse_press(global_pos, local_pos)
            event.accept()
            return
        
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """处理主窗口的鼠标释放事件"""
        if hasattr(self, '_click_through_enabled') and self._click_through_enabled:
            return super().mouseReleaseEvent(event)
        
        if event.button() == Qt.MouseButton.LeftButton:
            self.handle_mouse_release()
            event.accept()
            return
        
        super().mouseReleaseEvent(event)
    
    def eventFilter(self, obj, event):
        """事件过滤器"""
        if hasattr(self, '_click_through_enabled') and self._click_through_enabled:
            return super().eventFilter(obj, event)
        
        event_type = event.type()
        
        if obj != self.web_view and obj not in self.web_view.findChildren(QWidget):
            return super().eventFilter(obj, event)
        
        if event_type == QEvent.Type.MouseMove:
            mouse_event = event
            global_pos = mouse_event.globalPosition().toPoint()
            local_pos = self.mapFromGlobal(global_pos)
            
            if self.handle_mouse_move(global_pos, local_pos, mouse_event.buttons()):
                return True
            return False
        
        elif event_type == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                global_pos = mouse_event.globalPosition().toPoint()
                local_pos = self.mapFromGlobal(global_pos)
                if self.handle_mouse_press(global_pos, local_pos):
                    return True
        
        elif event_type == QEvent.Type.MouseButtonRelease:
            mouse_event = event
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                if self.handle_mouse_release():
                    return True
        
        return super().eventFilter(obj, event)
    
    # ==================== 窗口控制 ====================
    
    def set_window_size(self, width: int, height: int):
        """设置窗口大小"""
        self.resize(width, height)
    
    def set_window_position(self, x: int, y: int):
        """设置窗口位置"""
        self.move(x, y)
    
    def set_always_on_top(self, on_top: bool):
        """设置是否总是置顶"""
        flags = self.windowFlags()
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
    
    def set_opacity(self, opacity: float):
        """设置窗口透明度"""
        self.setWindowOpacity(max(0.0, min(1.0, opacity)))
