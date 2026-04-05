"""
JavaScript 通信模块

NOTE: Many methods in this module are invoked dynamically from JavaScript (QWebChannel)
or by external callers at runtime. They are intentionally public even if static
analysis reports them as "unused". Do NOT remove these APIs unless you confirm
there are no dynamic callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union, cast

from PyQt6.QtCore import QTimer, QUrl

from .logger import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from .widget import AvatarWidget


class JSCommunicationMixin:
    """JavaScript 通信功能 Mixin 类"""

    _page_ready: bool
    _pending_model: Optional[str]
    _pending_callback: Optional[Callable]

    def run_js(self, script: str, callback: Optional[Callable] = None):
        """执行 JavaScript 代码"""
        self = cast("AvatarWidget", self)
        if callback:
            self.web_page.runJavaScript(script, callback)
        else:
            self.web_page.runJavaScript(script)

    def load_model(self, model_path: str, callback: Optional[Callable[[bool], None]] = None):
        """
        加载 Live2D 模型

        Args:
            model_path: 模型文件路径
            callback: 加载结果回调
        """
        self = cast("AvatarWidget", self)
        resolved_path = model_path
        if not model_path.startswith(("http://", "https://", "file://")):
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

    def _do_load_model(self, model_path: str, callback: Optional[Callable[[bool], None]] = None):
        """实际执行模型加载"""
        self = cast("AvatarWidget", self)
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

    def change_expression(self, expression: Union[int, str]):
        """切换表情"""
        self = cast("AvatarWidget", self)
        script = f"setExpression('{expression}')" if isinstance(expression, str) else f"setExpression({expression})"
        self.run_js(script)

    def play_motion(self, group: str, index: Optional[int] = None):
        """播放动作"""
        self = cast("AvatarWidget", self)
        script = f"setMotion('{group}', {index})" if index is not None else f"setMotion('{group}')"
        self.run_js(script)

    def update_lip_sync(self, value: Union[float, dict[str, Any]]):
        """更新口型同步（兼容单值开合与 open/form 双参数）。"""
        self = cast("AvatarWidget", self)

        def _as_float(raw: Any, fallback: float) -> float:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return fallback

        if isinstance(value, dict):
            open_value = _as_float(value.get("open", value.get("value", 0.0)), 0.0)
            form_value = _as_float(value.get("form", 0.0), 0.0)
            open_value = max(0.0, min(1.0, open_value))
            form_value = max(-1.0, min(1.0, form_value))
            script = f"setMouthProfile({{open:{open_value:.4f}, form:{form_value:.4f}}})"
        else:
            open_value = max(0.0, min(1.0, _as_float(value, 0.0)))
            script = f"setMouth({open_value:.4f})"

        self.run_js(script)

    def play_audio(self, audio_path: str):
        """
        让浏览器播放音频并自动驱动口型同步

        Args:
            audio_path: 音频文件的绝对路径
        """
        self = cast("AvatarWidget", self)
        import os

        log_info(f"play_audio() called with: {audio_path}")  # 调试日志

        # 转为绝对路径并处理反斜杠
        abs_path = os.path.abspath(audio_path).replace("\\", "/")
        file_url = f"file:///{abs_path}"
        script = f"playAudio('{file_url}')"
        log_info(f"Executing JS: {script}")  # 调试日志
        self.run_js(script)
        log_info(f"Playing audio in browser: {file_url}")

    def stop_audio(self):
        """停止音频播放"""
        self = cast("AvatarWidget", self)
        self.run_js("stopAudio()")

    def get_model_info(self, callback: Callable[[dict], None]):
        """获取当前模型信息"""
        self = cast("AvatarWidget", self)
        self.run_js("getModelInfo()", callback)

    def set_model_position(self, x: int, y: int):
        """设置模型位置"""
        self = cast("AvatarWidget", self)
        script = f"setModelPosition({x}, {y})"
        self.run_js(script)

    def set_model_scale(self, scale: float):
        """设置模型缩放"""
        self = cast("AvatarWidget", self)
        scale = max(0.1, min(5.0, scale))
        script = f"setModelScale({scale})"
        self.run_js(script)

    def get_model_scale(self, callback: Callable[[float], None]):
        """获取当前模型缩放比例"""
        self = cast("AvatarWidget", self)
        self.run_js("getModelScale()", callback)

    def zoom_in(self, step: float = 0.1):
        """放大模型"""
        self = cast("AvatarWidget", self)
        script = f"zoomIn({step})"
        self.run_js(script)

    def zoom_out(self, step: float = 0.1):
        """缩小模型"""
        self = cast("AvatarWidget", self)
        script = f"zoomOut({step})"
        self.run_js(script)

    def reset_model(self):
        """重置模型"""
        self = cast("AvatarWidget", self)
        self.run_js("resetModel()")
