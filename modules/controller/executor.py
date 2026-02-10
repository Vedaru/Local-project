"""
执行模块 - PyAutoGUI 封装
负责实际执行电脑控制操作
"""

import subprocess
import os
import time
import pyautogui
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
        初始化执行器

        Args:
            failsafe: 是否开启 PyAutoGUI 防故障机制
        """
        pyautogui.FAILSAFE = failsafe
        self.failsafe = failsafe

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