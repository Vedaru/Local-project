"""
JavaScript 通信模块
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Callable

from PyQt6.QtCore import QUrl, QTimer

from .logger import log_info, log_warning, log_debug

if TYPE_CHECKING:
    from .widget import AvatarWidget


class JSCommunicationMixin:
    """JavaScript 通信功能 Mixin 类"""
    
    def run_js(self: 'AvatarWidget', script: str, callback: Optional[Callable] = None):
        """执行 JavaScript 代码"""
        if callback:
            self.web_page.runJavaScript(script, callback)
        else:
            self.web_page.runJavaScript(script)
    
    def load_model(self: 'AvatarWidget', model_path: str, callback: Optional[Callable[[bool], None]] = None):
        """
        加载 Live2D 模型
        
        Args:
            model_path: 模型文件路径
            callback: 加载结果回调
        """
        resolved_path = model_path
        if not model_path.startswith(('http://', 'https://', 'file://')):
            path = Path(model_path)
            if not path.is_absolute():
                current_dir = Path(__file__).parent.parent.parent
                path = current_dir / "assets" / "web" / "models" / model_path
            
            if path.exists():
                resolved_path = QUrl.fromLocalFile(str(path.resolve())).toString()
            else:
                log_warning(f"Model file not found: {path}")
                if callback:
                    callback(False)
                return
        
        if not self._page_ready:
            log_debug(f"Page not ready, queuing model: {resolved_path}")
            self._pending_model = resolved_path
            self._pending_callback = callback
            return
        
        self._do_load_model(resolved_path, callback)
    
    def _do_load_model(self: 'AvatarWidget', model_path: str, callback: Optional[Callable[[bool], None]] = None):
        """实际执行模型加载"""
        result_received = [False]
        
        def check_load_result():
            def on_check(result):
                if result and not result_received[0]:
                    result_received[0] = True
                    log_info(f"Model loaded: {model_path}")
                    if callback:
                        callback(True)
                elif not result_received[0]:
                    QTimer.singleShot(200, check_load_result)
            
            self.run_js("currentModel !== null", on_check)
        
        script = f"loadModel('{model_path}')"
        self.run_js(script)
        
        QTimer.singleShot(500, check_load_result)
        
        def on_timeout():
            if not result_received[0]:
                result_received[0] = True
                log_warning(f"Model load timeout: {model_path}")
                if callback:
                    callback(False)
        
        QTimer.singleShot(10000, on_timeout)
    
    def change_expression(self: 'AvatarWidget', expression: int | str):
        """切换表情"""
        if isinstance(expression, str):
            script = f"setExpression('{expression}')"
        else:
            script = f"setExpression({expression})"
        self.run_js(script)
    
    def play_motion(self: 'AvatarWidget', group: str, index: Optional[int] = None):
        """播放动作"""
        if index is not None:
            script = f"setMotion('{group}', {index})"
        else:
            script = f"setMotion('{group}')"
        self.run_js(script)
    
    def update_lip_sync(self: 'AvatarWidget', value: float):
        """更新口型同步"""
        value = max(0.0, min(1.0, value))
        script = f"setMouth({value})"
        self.run_js(script)
    
    def play_audio(self: 'AvatarWidget', audio_path: str):
        """
        让浏览器播放音频并自动驱动口型同步
        
        Args:
            audio_path: 音频文件的绝对路径
        """
        import os
        log_info(f"play_audio() called with: {audio_path}")  # 调试日志
        
        # 转为绝对路径并处理反斜杠
        abs_path = os.path.abspath(audio_path).replace("\\", "/")
        file_url = f"file:///{abs_path}"
        script = f"playAudio('{file_url}')"
        log_info(f"Executing JS: {script}")  # 调试日志
        self.run_js(script)
        log_info(f"Playing audio in browser: {file_url}")
    
    def stop_audio(self: 'AvatarWidget'):
        """停止音频播放"""
        self.run_js("stopAudio()")
    
    def get_model_info(self: 'AvatarWidget', callback: Callable[[dict], None]):
        """获取当前模型信息"""
        self.run_js("getModelInfo()", callback)
    
    def set_model_position(self: 'AvatarWidget', x: int, y: int):
        """设置模型位置"""
        script = f"setModelPosition({x}, {y})"
        self.run_js(script)
    
    def set_model_scale(self: 'AvatarWidget', scale: float):
        """设置模型缩放"""
        scale = max(0.1, min(5.0, scale))
        script = f"setModelScale({scale})"
        self.run_js(script)
    
    def get_model_scale(self: 'AvatarWidget', callback: Callable[[float], None]):
        """获取当前模型缩放比例"""
        self.run_js("getModelScale()", callback)
    
    def zoom_in(self: 'AvatarWidget', step: float = 0.1):
        """放大模型"""
        script = f"zoomIn({step})"
        self.run_js(script)
    
    def zoom_out(self: 'AvatarWidget', step: float = 0.1):
        """缩小模型"""
        script = f"zoomOut({step})"
        self.run_js(script)
    
    def reset_model(self: 'AvatarWidget'):
        """重置模型"""
        self.run_js("resetModel()")
