"""
执行模块 - PyAutoGUI 封装
负责实际执行电脑控制操作
"""

import subprocess
import os
import time
import pyautogui
import numpy as np
from typing import Optional
from ..logging_config import get_logger

logger = get_logger('ActionExecutor')


class ActionExecutor:
    """
    动作执行器类
    使用 PyAutoGUI 和 subprocess 执行电脑控制操作
    """

    def __init__(self, failsafe: bool = True):
        """
        初始化执行器，并尝试初始化 PaddleOCR（若可用）

        Args:
            failsafe: 是否开启 PyAutoGUI 防故障机制
        """
        pyautogui.FAILSAFE = failsafe
        self.failsafe = failsafe

        # 初始化 Tesseract OCR（使用 pytesseract + 系统 tesseract 二进制）
        # 我们默认使用环境变量 TESSERACT_CMD 指定 tesseract 可执行文件路径（优先），
        # 否则尝试在 PATH 中查找。若未找到，则 OCR 功能会被禁用并返回友好提示。
        self.ocr_available = False
        self.tesseract_cmd = os.getenv('TESSERACT_CMD', None)
        try:
            import pytesseract
            # 如果未通过环境变量指定，可尝试从 PATH 查找 tesseract 可执行文件
            if not self.tesseract_cmd:
                from shutil import which
                found = which('tesseract')
                if found:
                    self.tesseract_cmd = found
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
                self.ocr_available = True
                logger.info(f"Tesseract OCR 可用，cmd={self.tesseract_cmd}")
            else:
                # 未找到 tesseract 可执行文件
                logger.warning('Tesseract 可执行文件未找到（请安装 tesseract 并确保在 PATH 中，或设置环境变量 TESSERACT_CMD）。')
        except Exception as e:
            logger.warning(f"pytesseract 未安装或初始化失败，OCR 将被禁用：{e}")


    def open_app(self, path: str) -> str:
        """
        启动应用程序

        Args:
            path: 应用绝对路径

        Returns:
            str: 执行结果日志
        """
        try:
            logger.info(f"正在尝试启动应用: {path}")
            
            if os.name == 'nt':
                # Windows 平台使用 os.startfile 最为稳妥，相当于双击运行
                # 能够处理路径空格、关联程序以及权限请求
                os.startfile(path)
            else:
                # 其他平台使用 subprocess
                subprocess.Popen([path], shell=False)
            
            return f"✅ 成功启动应用: {path}"

        except Exception as e:
            logger.error(f"启动应用失败: {path}, 错误: {str(e)}")
            return f"❌ 启动应用失败: {path}, 错误: {str(e)}"

    def type_text(self, text: str) -> str:
        """
        模拟键盘输入文本

        Args:
            text: 要输入的文本

        Returns:
            str: 执行结果日志
        """
        try:
            # 对于中文等非ASCII字符，使用剪贴板粘贴更可靠
            import pyperclip
            original_clipboard = pyperclip.paste()  # 保存原始剪贴板内容
            
            pyperclip.copy(text)  # 复制文本到剪贴板
            pyautogui.hotkey('ctrl', 'v')  # 粘贴
            
            # 恢复原始剪贴板内容
            pyperclip.copy(original_clipboard)
            
            return f"✅ 成功输入文本: {text[:50]}{'...' if len(text) > 50 else ''}"

        except Exception as e:
            return f"❌ 输入文本失败, 错误: {str(e)}"

    def press_key(self, key: str) -> str:
        """
        模拟按键

        Args:
            key: 按键名称 (如 'enter', 'space', 'tab' 等)

        Returns:
            str: 执行结果日志
        """
        try:
            # 验证按键是否有效
            valid_keys = ['enter', 'space', 'tab', 'esc', 'backspace', 'delete',
                         'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown']

            if key.lower() not in valid_keys:
                return f"❌ 无效按键: {key}"

            pyautogui.press(key.lower())
            return f"✅ 成功按下按键: {key}"

        except Exception as e:
            return f"❌ 按键失败: {key}, 错误: {str(e)}"

    def save_note(self, content: str, filename: str = None) -> str:
        """
        保存笔记到桌面

        Args:
            content: 笔记内容
            filename: 文件名（可选，默认使用时间戳）

        Returns:
            str: 执行结果日志
        """
        try:
            import os
            from datetime import datetime
            
            # 获取桌面路径
            desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
            
            # 生成文件名
            if not filename:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'note_{timestamp}.txt'
            
            # 确保文件名有.txt扩展
            if not filename.endswith('.txt'):
                filename += '.txt'
            
            file_path = os.path.join(desktop_path, filename)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return f"✅ 成功保存笔记到桌面: {filename}"

        except Exception as e:
            return f"❌ 保存笔记失败, 错误: {str(e)}"

    def open_browser(self, url: str = None, browser_path: str = None) -> str:
        """
        打开浏览器并访问URL

        Args:
            url: 要访问的URL（可选，默认打开浏览器首页）
            browser_path: 浏览器路径（可选，使用默认浏览器）

        Returns:
            str: 执行结果日志
        """
        try:
            import webbrowser
            import subprocess
            
            if browser_path:
                # 使用指定浏览器
                if url:
                    subprocess.Popen([browser_path, url])
                else:
                    subprocess.Popen([browser_path])
                return f"✅ 成功打开浏览器: {browser_path}"
            else:
                # 使用默认浏览器
                if url:
                    webbrowser.open(url)
                    return f"✅ 成功打开默认浏览器访问: {url}"
                else:
                    webbrowser.open('about:blank')
                    return "✅ 成功打开默认浏览器"

        except Exception as e:
            return f"❌ 打开浏览器失败, 错误: {str(e)}"

    def find_text_on_screen(self, keyword: Optional[str] = None, min_confidence: float = 0.3):
        """
        使用 Tesseract（pytesseract）扫描当前屏幕并返回识别文本与中心坐标。

        返回格式与之前保持一致，便于上层无缝调用：
        - keyword 为 None 时返回列表: [{"text": str, "confidence": float (0-1), "x": int, "y": int, "box": [[x,y],...]}, ...]
        - keyword 提供时返回第一个匹配到的 dict 或 None

        说明：
        - 置信度由 pytesseract 的 conf（0-100）映射为 0-1
        - 如果系统未安装 Tesseract 或 pytesseract 不可用，将返回空列表或 None（不会抛异常）
        """
        try:
            if not getattr(self, 'ocr_available', False):
                logger.warning("OCR 未启用（找不到 tesseract 或 pytesseract 未安装）")
                return None if keyword else []

            # 截取屏幕（PIL.Image）
            img = pyautogui.screenshot()

            # 延迟导入 pytesseract，避免模块导入阶段出现依赖错误
            import pytesseract
            from pytesseract import Output

            # 优先使用环境变量指定的语言（例如：'chi_sim+eng'），如果未安装指定语言，pytesseract 会抛异常，我们捕获并回退
            lang = os.getenv('TESSERACT_LANG', '')
            try:
                if lang:
                    data = pytesseract.image_to_data(img, output_type=Output.DICT, lang=lang)
                else:
                    data = pytesseract.image_to_data(img, output_type=Output.DICT)
            except Exception:
                # 回退到默认识别（不指定 lang）
                data = pytesseract.image_to_data(img, output_type=Output.DICT)

            n = len(data.get('text', []))
            items = []
            for i in range(n):
                txt = (data['text'][i] or '').strip()
                if not txt:
                    continue

                # pytesseract 返回的 conf 字段有时为 '-1' 或字符串；安全转换
                try:
                    conf_raw = float(data['conf'][i])
                except Exception:
                    conf_raw = -1.0

                # 将置信度映射到 0-1（pytesseract 的 conf 是 0-100）
                conf = max(0.0, min(100.0, conf_raw)) / 100.0 if conf_raw >= 0 else 0.0
                if conf < float(min_confidence):
                    continue

                left = int(data['left'][i])
                top = int(data['top'][i])
                width = int(data['width'][i])
                height = int(data['height'][i])
                cx = int(left + width / 2)
                cy = int(top + height / 2)

                box = [[left, top], [left + width, top], [left + width, top + height], [left, top + height]]
                items.append({
                    'text': txt,
                    'confidence': conf,
                    'x': cx,
                    'y': cy,
                    'box': box
                })

            if keyword:
                key_norm = str(keyword).strip().lower()
                for it in items:
                    if key_norm in it['text'].lower():
                        return it
                return None

            return items

        except Exception as e:
            logger.error(f"Tesseract OCR 识别出错: {e}", exc_info=True)
            return None if keyword else []

    def click_text(self, text: str, clicks: int = 1, interval: float = 0.0, button: str = 'left') -> str:
        """
        在屏幕上查找包含指定 `text` 的文本框并点击其中心点（基于 Tesseract OCR）。

        返回友好的执行结果字符串（便于上层记录与 LLM 展示）。
        """
        try:
            if not getattr(self, 'ocr_available', False):
                return "❌ OCR 功能未启用（请安装 tesseract 二进制并确保 pytesseract 可用）"

            found = self.find_text_on_screen(keyword=text)
            if not found:
                return f"❌ 未在屏幕上找到文本: {text}"

            x, y = found['x'], found['y']
            # 移动并点击，保留 PyAutoGUI 的 failsafe
            pyautogui.moveTo(x, y, duration=0.15)
            pyautogui.click(x, y, clicks=clicks, interval=interval, button=button)
            return f"✅ 已点击文本 '{found['text']}' (坐标: {x},{y}, 置信度: {found.get('confidence',0):.2f})"

        except Exception as e:
            logger.error(f"点击识别文本失败: {e}", exc_info=True)
            return f"❌ 点击失败: {str(e)}"