"""
AgentTools — 为 ManusAgent 提供的工具箱包装
- 联网搜索（duckduckgo-search）
- 文件读写（read_file / write_file）
- 本地电脑控制（包装现有的 ComputerController / ActionExecutor）
- 浏览器访问（包装 WebSurfer）

所有方法均返回字符串（便于在 Agent 的 Observation 中拼接与展示）。
"""
from typing import Optional, Any, Dict
import os
import json

import pyautogui

from modules.controller import ComputerController
from .browser import WebSurfer

# 使用国内可用的搜索抓取（优先 Bing 中国站 cn.bing.com）
# duckduckgo 已被替换为静态爬虫方式（requests + BeautifulSoup），以适配中国大陆网络环境
import requests
from bs4 import BeautifulSoup


class AgentTools:
    """将若干工具以方法形式暴露给 Agent 使用。可接受已有的 ComputerController 实例。"""

    def __init__(self, controller: Optional[ComputerController] = None, browser: Optional[WebSurfer] = None):
        self.controller = controller
        # WebSurfer 使用 prefer_drission 与 timeout 参数；移除不存在的 headless 参数
        self.browser = browser or WebSurfer(prefer_drission=False)

    # ---------------- 网络搜索 ----------------
    def search(self, query: str, max_results: int = 5) -> str:
        """使用 cn.bing.com 静态抓取来返回简短的搜索结果摘要（国内可直连）。

        返回值与原 ddg 相似：列表文本，每条包含标题、链接与简要描述。
        如 cn.bing.com 无结果，会尝试回退到百度（简单抓取）。
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/115.0 Safari/537.36'
            }
            params = {'q': query}
            resp = requests.get('https://cn.bing.com/search', params=params, headers=headers, timeout=8)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for i, li in enumerate(soup.select('li.b_algo')[:max_results], start=1):
                a = li.find('h2') and li.find('h2').find('a')
                title = a.get_text(strip=True) if a else ''
                href = a['href'] if a and a.has_attr('href') else ''
                snippet_tag = li.select_one('.b_caption p') or li.find('p')
                body = snippet_tag.get_text(strip=True) if snippet_tag else ''
                items.append(f"{i}. {title} — {href}\n   {body}")

            if not items:
                # 回退到百度搜索（简单解析）
                resp2 = requests.get('https://www.baidu.com/s', params={'wd': query}, headers=headers, timeout=8)
                soup2 = BeautifulSoup(resp2.text, 'html.parser')
                for i, div in enumerate(soup2.select('div.result')[:max_results], start=1):
                    title_tag = div.find('h3') or div.find('a')
                    title = title_tag.get_text(strip=True) if title_tag else ''
                    href = ''
                    snippet_tag = div.find('div', class_='c-abstract') or div.find('p')
                    body = snippet_tag.get_text(strip=True) if snippet_tag else ''
                    items.append(f"{i}. {title} — {href}\n   {body}")

            return "\n".join(items) if items else "🔍 未找到相关结果。"
        except Exception as e:
            return f"❌ 搜索错误: {str(e)}"

    # ---------------- 浏览器 ----------------
    def browse(self, url: str) -> str:
        """调用 WebSurfer.browse 并返回文本摘要（使用 requests + BeautifulSoup，适合国内环境）"""
        try:
            page = self.browser.browse(url)
            text = page.get('text') if isinstance(page, dict) else str(page)
            title = page.get('title', '') if isinstance(page, dict) else ''
            snippet = (text or '')[:400].replace('\n', ' ')
            return f"🔗 {title} — {url}\n{snippet}{'...' if len(text or '') > 400 else ''}"
        except Exception as e:
            return f"❌ 浏览失败: {str(e)}"

    # ---------------- 文件操作 ----------------
    def read_file(self, path: str) -> str:
        try:
            if not os.path.exists(path):
                return f"❌ 文件不存在: {path}"
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"❌ 读取文件失败: {str(e)}"

    def write_file(self, path: str, content: str) -> str:
        try:
            dirp = os.path.dirname(path)
            if dirp:
                os.makedirs(dirp, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"✅ 已写入: {path}"
        except Exception as e:
            return f"❌ 写入文件失败: {str(e)}"

    # ---------------- 电脑控制（包装现有 ComputerController） ----------------
    def open_local_app(self, app_path: str) -> str:
        """通过 ComputerController 执行打开应用；若 controller 不可用，尝试直接调用 pyautogui / os 启动"""
        try:
            if self.controller:
                # 使用已有的 Controller 的内部执行接口（构造 action dict）
                return self.controller._execute_action({'action': 'open_app', 'app_path': app_path})
            # 兜底：直接使用 os.startfile（仅 Windows）
            if os.name == 'nt':
                os.startfile(app_path)
                return f"✅ 成功启动应用（直接）：{app_path}"
            else:
                os.system(f'"{app_path}" &')
                return f"✅ 成功尝试启动应用（直接）：{app_path}"
        except Exception as e:
            return f"❌ 启动应用失败: {str(e)}"

    def click_screen(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left') -> str:
        """模拟鼠标点击（直接使用 pyautogui）"""
        try:
            if x is None or y is None:
                pyautogui.click(button=button)
            else:
                pyautogui.click(x=x, y=y, button=button)
            return f"✅ 点击屏幕: ({x},{y}) button={button}"
        except Exception as e:
            return f"❌ 点击失败: {str(e)}"

    # ---------------- 通用执行接口 ----------------
    def execute(self, tool: str, args: Any) -> str:
        """高层调度：将 tool 名和 args 映射到具体方法并返回字符串结果"""
        try:
            tool = (tool or '').lower()
            if tool == 'search':
                q = args if isinstance(args, str) else args.get('query', '')
                return self.search(q)
            if tool == 'browse':
                url = args if isinstance(args, str) else args.get('url', '')
                return self.browse(url)
            if tool == 'read_file':
                path = args if isinstance(args, str) else args.get('path', '')
                return self.read_file(path)
            if tool == 'write_file':
                if isinstance(args, str):
                    return "❌ write_file 需要提供 path 与 content 的对象格式"
                path = args.get('path')
                content = args.get('content', '')
                return self.write_file(path, content)
            if tool == 'open_local_app':
                path = args if isinstance(args, str) else args.get('app_path')
                return self.open_local_app(path)

            if tool == 'click_screen':
                if isinstance(args, dict):
                    return self.click_screen(args.get('x'), args.get('y'), args.get('button', 'left'))
                return self.click_screen()

            # ------------- OCR 工具（调用 controller 的 OCR 能力） -------------
            if tool == 'ocr_scan':
                """扫描屏幕并返回识别到的文字列表（JSON 字符串）。"""
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 OCR 扫描"
                items = self.controller.action_executor.find_text_on_screen()
                if items is None:
                    return "🔍 OCR 未初始化或未识别到文本。"
                try:
                    return json.dumps(items, ensure_ascii=False)
                except Exception:
                    return str(items)

            if tool == 'ocr_click':
                """查找包含指定文本的屏幕项并点击（args 支持字符串或 {"text": ...}）"""
                if isinstance(args, str):
                    target = args
                else:
                    target = (args or {}).get('text')
                if not target:
                    return "❌ ocr_click 需要提供 text 参数"
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 ocr_click"
                return self.controller.action_executor.click_text(target)

            if tool in ('final_answer', 'final'):
                # Agent 自身不再调用此工具；上层将识别 tool 为 final_answer 并结束循环
                return str(args)

            return f"❌ 未知工具: {tool}"
        except Exception as e:
            return f"❌ 工具执行异常: {str(e)}"
