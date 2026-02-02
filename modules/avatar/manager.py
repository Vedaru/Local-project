"""
Avatar 管理器 - 用于在子线程中安全地控制 Avatar
"""

from typing import Optional, Callable

from PyQt6.QtWidgets import QApplication

from .widget import AvatarWidget
from .logger import log_info


class AvatarManager:
    """
    Avatar 管理器 - 用于在子线程中安全地控制 Avatar
    
    由于 PyQt 的 GUI 必须在主线程运行，此管理器提供线程安全的方法
    """
    
    def __init__(self):
        self.widget: Optional[AvatarWidget] = None
        self._app: Optional[QApplication] = None
    
    def create_widget(
        self,
        width: int = 400,
        height: int = 600,
        x: int = 100,
        y: int = 100
    ) -> AvatarWidget:
        """
        创建 Avatar 窗口（必须在主线程调用）
        """
        self.widget = AvatarWidget(width, height, x, y)
        log_info(f"AvatarManager created widget ({width}x{height} at {x},{y})")
        return self.widget
    
    def show(self):
        """显示窗口"""
        if self.widget:
            self.widget.show()
    
    def hide(self):
        """隐藏窗口"""
        if self.widget:
            self.widget.hide()
    
    def load_model(self, model_path: str, callback: Optional[Callable] = None):
        """加载模型"""
        if self.widget:
            self.widget.load_model(model_path, callback)
    
    def update_lip_sync(self, value: float):
        """更新口型"""
        if self.widget:
            self.widget.update_lip_sync(value)
    
    def change_expression(self, expression: int | str):
        """切换表情"""
        if self.widget:
            self.widget.change_expression(expression)
    
    def play_motion(self, group: str, index: Optional[int] = None):
        """播放动作"""
        if self.widget:
            self.widget.play_motion(group, index)
