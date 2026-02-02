"""
窗口调整大小模块
"""

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QEvent
from PyQt6.QtWidgets import QWidget

from .logger import log_debug

if TYPE_CHECKING:
    from .widget import AvatarWidget


class ResizeMixin:
    """窗口调整大小功能 Mixin 类"""
    
    def init_resize_state(self: 'AvatarWidget'):
        """初始化调整大小状态"""
        self._resize_edge: Optional[str] = None
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None
        self._edge_margin = 20
        self._is_dragging = False
        self._drag_position: Optional[QPoint] = None
    
    def get_edge_at_pos(self: 'AvatarWidget', pos: QPoint) -> Optional[str]:
        """
        检测鼠标位置对应的窗口边缘
        返回: 'left', 'right', 'top', 'bottom', 'top-left', 'top-right', 'bottom-left', 'bottom-right', 或 None
        """
        rect = self.rect()
        margin = self._edge_margin
        
        left = pos.x() < margin
        right = pos.x() > rect.width() - margin
        top = pos.y() < margin
        bottom = pos.y() > rect.height() - margin
        
        if top and left:
            return 'top-left'
        elif top and right:
            return 'top-right'
        elif bottom and left:
            return 'bottom-left'
        elif bottom and right:
            return 'bottom-right'
        elif left:
            return 'left'
        elif right:
            return 'right'
        elif top:
            return 'top'
        elif bottom:
            return 'bottom'
        return None
    
    def update_cursor_for_edge(self: 'AvatarWidget', edge: Optional[str]):
        """根据边缘类型更新鼠标光标"""
        cursor_map = {
            'left': Qt.CursorShape.SizeHorCursor,
            'right': Qt.CursorShape.SizeHorCursor,
            'top': Qt.CursorShape.SizeVerCursor,
            'bottom': Qt.CursorShape.SizeVerCursor,
            'top-left': Qt.CursorShape.SizeFDiagCursor,
            'bottom-right': Qt.CursorShape.SizeFDiagCursor,
            'top-right': Qt.CursorShape.SizeBDiagCursor,
            'bottom-left': Qt.CursorShape.SizeBDiagCursor,
        }
        if edge and edge in cursor_map:
            self.setCursor(cursor_map[edge])
            if hasattr(self, 'web_view'):
                self.web_view.setCursor(cursor_map[edge])
        else:
            self.unsetCursor()
            if hasattr(self, 'web_view'):
                self.web_view.unsetCursor()
    
    def do_resize(self: 'AvatarWidget', global_pos: QPoint):
        """执行窗口调整大小"""
        if not self._resize_start_geometry or not self._resize_start_pos:
            return
        
        delta = global_pos - self._resize_start_pos
        geo = self._resize_start_geometry
        new_geo = QRect(geo)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        
        edge = self._resize_edge
        
        # 记录调整前的实际窗口位置
        current_geo = self.geometry()
        old_left = current_geo.left()
        old_top = current_geo.top()
        
        if 'left' in edge:
            new_left = geo.left() + delta.x()
            new_width = geo.right() - new_left + 1
            if new_width >= min_w:
                new_geo.setLeft(new_left)
        
        if 'right' in edge:
            new_width = geo.width() + delta.x()
            if new_width >= min_w:
                new_geo.setWidth(new_width)
        
        if 'top' in edge:
            new_top = geo.top() + delta.y()
            new_height = geo.bottom() - new_top + 1
            if new_height >= min_h:
                new_geo.setTop(new_top)
        
        if 'bottom' in edge:
            new_height = geo.height() + delta.y()
            if new_height >= min_h:
                new_geo.setHeight(new_height)
        
        self.setGeometry(new_geo)
        
        # 计算这一帧的实际位移
        dx = new_geo.left() - old_left
        dy = new_geo.top() - old_top
        
        if dx != 0 or dy != 0:
            # 通知 JavaScript 调整模型位置来补偿窗口位置变化
            self.run_js(f"compensateModelPosition({dx}, {dy})")
    
    def handle_mouse_move(self: 'AvatarWidget', global_pos: QPoint, local_pos: QPoint, buttons) -> bool:
        """处理鼠标移动事件，返回是否已处理"""
        # 如果正在调整大小
        if self._resize_edge and self._resize_start_pos:
            self.do_resize(global_pos)
            return True
        
        # 如果正在拖拽窗口
        if self._is_dragging and self._drag_position is not None:
            if buttons & Qt.MouseButton.LeftButton:
                new_pos = global_pos - self._drag_position
                self.move(new_pos)
            return True
        
        # 检测边缘并更新光标
        edge = self.get_edge_at_pos(local_pos)
        self.update_cursor_for_edge(edge)
        return False
    
    def handle_mouse_press(self: 'AvatarWidget', global_pos: QPoint, local_pos: QPoint) -> bool:
        """处理鼠标按下事件，返回是否已处理"""
        edge = self.get_edge_at_pos(local_pos)
        
        if edge:
            # 开始调整大小
            self._resize_edge = edge
            self._resize_start_pos = global_pos
            self._resize_start_geometry = self.geometry()
            return True
        else:
            # 开始拖拽
            self._is_dragging = True
            self._drag_position = global_pos - self.frameGeometry().topLeft()
            return False
    
    def handle_mouse_release(self: 'AvatarWidget') -> bool:
        """处理鼠标释放事件，返回是否正在调整大小"""
        was_resizing = self._resize_edge is not None
        self._is_dragging = False
        self._drag_position = None
        self._resize_edge = None
        self._resize_start_pos = None
        self._resize_start_geometry = None
        return was_resizing
