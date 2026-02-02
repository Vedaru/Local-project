"""
Windows 点击穿透功能模块
"""

import sys
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget

from .logger import log_info, log_warning, log_error, log_debug

if TYPE_CHECKING:
    from .widget import AvatarWidget


class ClickThroughMixin:
    """点击穿透功能 Mixin 类"""
    
    def setup_click_through(self: 'AvatarWidget'):
        """设置 Windows 窗口点击穿透"""
        if sys.platform != 'win32':
            return
        
        try:
            import ctypes
            
            # Windows API 常量
            self._GWL_EXSTYLE = -20
            self._WS_EX_LAYERED = 0x00080000
            self._WS_EX_TRANSPARENT = 0x00000020
            self._user32 = ctypes.windll.user32
            
            # 默认禁用点击穿透（可拖拽模式）
            self._click_through_enabled = False
            self._click_through_setup_done = True
            
            # 设置全局热键
            self._setup_global_hotkey()
            
        except Exception as e:
            log_warning(f"Failed to setup click-through: {e}")
            self._click_through_enabled = False
            self._click_through_setup_done = False
    
    def _setup_global_hotkey(self: 'AvatarWidget'):
        """设置全局热键 Alt+D"""
        try:
            import ctypes
            from ctypes import wintypes
            
            # 热键常量
            self._MOD_ALT = 0x0001
            self._HOTKEY_ID = 1
            self._VK_D = 0x44
            
            # 注册全局热键 Alt+D
            result = self._user32.RegisterHotKey(
                None,
                self._HOTKEY_ID,
                self._MOD_ALT,
                self._VK_D
            )
            
            if result:
                # 使用定时器轮询热键消息
                self._hotkey_timer = QTimer(self)
                self._hotkey_timer.timeout.connect(self._check_hotkey)
                self._hotkey_timer.start(100)
                log_info("Global hotkey Alt+D registered")
            else:
                log_warning("Failed to register global hotkey (may already be in use)")
                
        except Exception as e:
            log_warning(f"Failed to setup global hotkey: {e}")
    
    def _check_hotkey(self: 'AvatarWidget'):
        """检查全局热键是否被按下"""
        try:
            import ctypes
            from ctypes import wintypes, byref
            
            WM_HOTKEY = 0x0312
            PM_REMOVE = 0x0001
            
            class MSG(ctypes.Structure):
                _fields_ = [
                    ('hwnd', wintypes.HWND),
                    ('message', wintypes.UINT),
                    ('wParam', wintypes.WPARAM),
                    ('lParam', wintypes.LPARAM),
                    ('time', wintypes.DWORD),
                    ('pt', wintypes.POINT),
                ]
            
            msg = MSG()
            if self._user32.PeekMessageW(byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                if msg.message == WM_HOTKEY and msg.wParam == self._HOTKEY_ID:
                    log_debug("Hotkey Alt+D detected")
                    self.toggle_click_through()
                    
        except Exception as e:
            log_error(f"Hotkey check error: {e}")
    
    def cleanup_global_hotkey(self: 'AvatarWidget'):
        """清理全局热键"""
        try:
            if hasattr(self, '_hotkey_timer'):
                self._hotkey_timer.stop()
            if hasattr(self, '_HOTKEY_ID') and hasattr(self, '_user32'):
                self._user32.UnregisterHotKey(None, self._HOTKEY_ID)
        except:
            pass
    
    def apply_click_through(self: 'AvatarWidget'):
        """应用点击穿透设置"""
        try:
            self._hwnd = int(self.winId())
            self._update_click_through()
        except Exception as e:
            log_warning(f"Failed to apply click-through: {e}")
    
    def _update_click_through(self: 'AvatarWidget'):
        """更新点击穿透状态"""
        try:
            current_geometry = self.geometry()
            was_visible = self.isVisible()
            
            base_flags = (
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            
            if self._click_through_enabled:
                new_flags = base_flags | Qt.WindowType.WindowTransparentForInput
            else:
                new_flags = base_flags
            
            self.setWindowFlags(new_flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setGeometry(current_geometry)
            
            if was_visible:
                self.show()
            
            # Windows API 备用设置
            if hasattr(self, '_hwnd') and hasattr(self, '_user32'):
                self._hwnd = int(self.winId())
                self._set_window_click_through(self._hwnd, self._click_through_enabled)
                
                if hasattr(self, 'web_view'):
                    self.web_view.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents, 
                        self._click_through_enabled
                    )
                    for child in self.web_view.findChildren(QWidget):
                        child.setAttribute(
                            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                            self._click_through_enabled
                        )
                    self._set_all_child_windows_click_through(self._hwnd, self._click_through_enabled)
                    
        except Exception as e:
            log_warning(f"Failed to update click-through: {e}")
    
    def _set_all_child_windows_click_through(self: 'AvatarWidget', parent_hwnd, enabled):
        """递归设置所有子窗口的点击穿透"""
        import ctypes
        from ctypes import wintypes
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        child_windows = []
        
        def enum_callback(hwnd, lparam):
            child_windows.append(hwnd)
            return True
        
        callback = WNDENUMPROC(enum_callback)
        self._user32.EnumChildWindows(parent_hwnd, callback, 0)
        
        for child_hwnd in child_windows:
            try:
                self._set_window_click_through(child_hwnd, enabled)
            except:
                pass
    
    def _set_window_click_through(self: 'AvatarWidget', hwnd, enabled):
        """设置指定窗口的点击穿透"""
        current_style = self._user32.GetWindowLongW(hwnd, self._GWL_EXSTYLE)
        
        if enabled:
            new_style = current_style | self._WS_EX_LAYERED | self._WS_EX_TRANSPARENT
        else:
            new_style = (current_style | self._WS_EX_LAYERED) & ~self._WS_EX_TRANSPARENT
        
        self._user32.SetWindowLongW(hwnd, self._GWL_EXSTYLE, new_style)
        
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        self._user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
    
    def toggle_click_through(self: 'AvatarWidget'):
        """切换点击穿透模式"""
        if hasattr(self, '_click_through_enabled'):
            self._click_through_enabled = not self._click_through_enabled
            self._update_click_through()
            
            # 更新托盘菜单文本
            if hasattr(self, 'drag_action'):
                if self._click_through_enabled:
                    self.drag_action.setText("🔓 启用拖拽模式")
                else:
                    self.drag_action.setText("🔒 启用穿透模式")
            
            status = "enabled (drag disabled)" if self._click_through_enabled else "disabled (drag enabled)"
            log_info(f"Click-through {status}")
            return self._click_through_enabled
        return None
    
    def set_click_through(self: 'AvatarWidget', enabled: bool):
        """设置点击穿透状态"""
        if hasattr(self, '_click_through_enabled'):
            self._click_through_enabled = enabled
            self._update_click_through()
