"""
系统托盘模块
"""

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QColor, QIcon, QAction, QPixmap, QPainter

from .logger import log_info

if TYPE_CHECKING:
    from .widget import AvatarWidget


class TrayMixin:
    """系统托盘功能 Mixin 类"""
    
    def setup_tray(self: 'AvatarWidget'):
        """设置系统托盘图标"""
        # 创建托盘图标（简单的彩色圆形）
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(100, 200, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        
        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), self)
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        # 切换拖拽模式
        self.drag_action = QAction("🔓 启用拖拽模式", self)
        self.drag_action.triggered.connect(self._on_toggle_drag)
        tray_menu.addAction(self.drag_action)
        
        tray_menu.addSeparator()
        
        # 显示/隐藏窗口
        show_action = QAction("👁 显示/隐藏", self)
        show_action.triggered.connect(self._on_toggle_visibility)
        tray_menu.addAction(show_action)
        
        # 重置位置和大小
        reset_pos_action = QAction("📍 重置位置和大小", self)
        reset_pos_action.triggered.connect(self._reset_window)
        tray_menu.addAction(reset_pos_action)
        
        tray_menu.addSeparator()
        
        # 退出
        quit_action = QAction("❌ 退出", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip("Live2D Avatar\n右键点击查看菜单\n左键点击切换拖拽模式")
        
        # 左键点击切换拖拽模式
        self.tray_icon.activated.connect(self._on_tray_activated)
        
        self.tray_icon.show()
        log_info("System tray initialized")
    
    def _on_tray_activated(self: 'AvatarWidget', reason):
        """托盘图标点击事件"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_toggle_drag()
    
    def _on_toggle_drag(self: 'AvatarWidget'):
        """切换拖拽模式"""
        result = self.toggle_click_through()
        if result is not None:
            if result:
                self.drag_action.setText("🔓 启用拖拽模式")
                self.tray_icon.showMessage(
                    "Avatar", 
                    "点击穿透模式 - 可以点击模型后面的窗口", 
                    QSystemTrayIcon.MessageIcon.Information, 
                    2000
                )
            else:
                self.drag_action.setText("🔒 禁用拖拽模式")
                self.tray_icon.showMessage(
                    "Avatar", 
                    "拖拽模式 - 可以拖动窗口位置", 
                    QSystemTrayIcon.MessageIcon.Information, 
                    2000
                )
    
    def _on_toggle_visibility(self: 'AvatarWidget'):
        """切换窗口可见性"""
        if self.isVisible():
            self.hide()
            log_info("Window hidden")
        else:
            self.show()
            log_info("Window shown")
    
    def _reset_window(self: 'AvatarWidget'):
        """重置窗口位置和大小到初始值"""
        self.setGeometry(
            self._initial_x,
            self._initial_y,
            self._initial_width,
            self._initial_height
        )
        # 同时重置模型缩放
        self.run_js("resetModelScale()")
        log_info(f"Window reset to ({self._initial_x}, {self._initial_y}, {self._initial_width}x{self._initial_height})")
