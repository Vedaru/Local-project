"""
AgentTools — 为 ManusAgent 提供的工具箱包装
- 联网搜索（duckduckgo-search）
- 文件读写（read_file / write_file）
- 本地电脑控制（包装现有的 ComputerController / ActionExecutor）
- 浏览器访问（包装 WebSurfer）

所有方法均返回字符串（便于在 Agent 的 Observation 中拼接与展示）。
"""
from typing import Optional, Any
import os

import pyautogui

from modules.controller import ComputerController
from .browser import WebSurfer

# 使用国内可用的搜索抓取（优先百度 https://www.baidu.com/s）
# duckduckgo 已被替换为静态爬虫方式（requests + BeautifulSoup），以适配中国大陆网络环境
import requests
from bs4 import BeautifulSoup


class AgentTools:
    """将若干工具以方法形式暴露给 Agent 使用。可接受已有的 ComputerController 实例。"""

    def __init__(self, controller: Optional[ComputerController] = None, browser: Optional[WebSurfer] = None):
        self.controller = controller
        # WebSurfer 使用 prefer_drission 与 timeout 参数；移除不存在的 headless 参数
        self.browser = browser or WebSurfer()

    # ---------------- 网络搜索 ----------------
    def search(self, query: str, max_results: int = 5) -> str:
        """使用百度静态抓取来返回简短的搜索结果摘要（国内可直连）。

        返回值与原 ddg 相似：列表文本，每条包含标题、链接与简要描述。
        如百度无结果，直接返回“未找到相关结果”（不回退到 Bing）。
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/115.0 Safari/537.36'
            }
            # 直接使用百度作为默认抓取目标（不再修改 mkt/Accept-Language）
            resp = requests.get('https://www.baidu.com/s', params={'wd': query}, headers=headers, timeout=8)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for i, div in enumerate(soup.select('div.result')[:max_results], start=1):
                title_tag = div.find('h3') or div.find('a')
                title = title_tag.get_text(strip=True) if title_tag else ''
                href = ''
                snippet_tag = div.find('div', class_='c-abstract') or div.find('p')
                body = snippet_tag.get_text(strip=True) if snippet_tag else ''
                items.append(f"{i}. {title} — {href}\n   {body}")

            if not items:
                # 不再回退到 Bing；如果百度无结果则直接返回空提示
                return "🔍 未找到相关结果。"

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

            # ------------- DOM（替代 OCR）工具 -------------
            if tool == 'dom_open':
                """打开 Playwright 浏览器并导航（args 支持字符串 url 或对象 {url, browser_type, headless, browser_path}）"""
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_open"
                if isinstance(args, str):
                    url = args
                    browser_type = None
                    headless = False
                    browser_path = None
                else:
                    url = (args or {}).get('url')
                    browser_type = (args or {}).get('browser_type')
                    headless = bool((args or {}).get('headless', False))
                    browser_path = (args or {}).get('browser_path')
                # 规范化：若传入显式的 Google 搜索链接，则改写为百度（双层保险，避免 LLM 直接生成 google 搜索 URL）
                try:
                    if url:
                        from urllib.parse import urlparse, parse_qs, urlencode
                        p = urlparse(url)
                        hostname = (p.hostname or '').lower()
                        path = p.path or ''
                        # 若传入的是裸词（没有 scheme/netloc），将其规范为百度搜索
                        if not p.scheme or not p.netloc:
                            url = 'https://www.baidu.com/s?' + urlencode({'wd': url})
                            p = urlparse(url)
                            hostname = (p.hostname or '').lower()
                            path = p.path or ''
                        # 若为 Google 搜索，重写为百度搜索（保留 q 参数）
                        if 'google.' in hostname and path.startswith('/search'):
                            qs = parse_qs(p.query)
                            qval = qs.get('q', [''])[0]
                            url = 'https://www.baidu.com/s?' + urlencode({'wd': qval}) if qval else 'https://www.baidu.com'
                except Exception:
                    pass
                return self.controller._execute_action({'action': 'dom_open', 'url': url, 'browser_type': browser_type, 'headless': headless, 'browser_path': browser_path})

            if tool == 'dom_navigate':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_navigate"
                url = args if isinstance(args, str) else (args or {}).get('url')
                if not url:
                    return "❌ dom_navigate 需要提供 url 参数"
                return self.controller._execute_action({'action': 'dom_navigate', 'url': url})

            if tool == 'dom_status':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_status"
                return self.controller._execute_action({'action': 'dom_status'})

            if tool == 'dom_fill':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_fill"
                if isinstance(args, str):
                    return "❌ dom_fill 需要提供对象格式：{selector, value}"
                selector = (args or {}).get('selector')
                value = (args or {}).get('value', '')
                by = (args or {}).get('by', 'css')
                if not selector:
                    return "❌ dom_fill 需要提供 selector 参数"
                return self.controller._execute_action({'action': 'dom_fill', 'selector': selector, 'value': value, 'by': by})

            if tool == 'dom_eval':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_eval"
                expr = args if isinstance(args, str) else (args or {}).get('expression')
                if not expr:
                    return "❌ dom_eval 需要提供 expression/字符串参数"
                return self.controller._execute_action({'action': 'dom_eval', 'expression': expr})

            if tool == 'dom_query':
                """在当前 DOM 页面上按选择器查询元素并返回结果（JSON 字符串）。

                args 可以是字符串（作为 selector）或对象 {selector, by, multiple}
                若未提供 selector，则默认返回 body 的文本片段。
                """
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_query"
                if isinstance(args, str):
                    selector = args
                    by = 'css'
                    multiple = False
                else:
                    selector = (args or {}).get('selector', 'body')
                    by = (args or {}).get('by', 'css')
                    multiple = bool((args or {}).get('multiple', False))
                res = self.controller._execute_action({'action': 'dom_query', 'selector': selector, 'by': by, 'multiple': multiple})
                return res

            if tool == 'dom_preview':
                """列出匹配 selector 的候选项（供用户/Agent 先确认再点击）"""
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_preview"
                if isinstance(args, str):
                    selector = args
                    by = 'css'
                    max_results = 6
                else:
                    selector = (args or {}).get('selector')
                    by = (args or {}).get('by', 'css')
                    max_results = int((args or {}).get('max_results', 6))
                if not selector:
                    return "❌ dom_preview 需要提供 selector 参数"
                return self.controller._execute_action({'action': 'dom_preview', 'selector': selector, 'by': by, 'max_results': max_results})

            if tool == 'dom_click':
                """在当前 DOM 页面上点击指定选择器（args 支持字符串或 {selector, by, index, timeout}）"""
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_click"
                if isinstance(args, str):
                    selector = args
                    by = 'css'
                    index = None
                    timeout = 5
                else:
                    selector = (args or {}).get('selector')
                    by = (args or {}).get('by', 'css')
                    index = (args or {}).get('index', None)
                    timeout = int((args or {}).get('timeout', 5))
                if not selector:
                    return "❌ dom_click 需要提供 selector 参数"
                payload = {'action': 'dom_click', 'selector': selector, 'by': by, 'timeout': timeout}
                if index is not None:
                    payload['index'] = int(index)
                return self.controller._execute_action(payload)

            if tool == 'dom_open_and_click':
                """在页面打开后等待 selector 出现并点击第一个匹配项；args 支持 {url, selector, by, timeout}"""
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 dom_open_and_click"
                if isinstance(args, str):
                    return "❌ dom_open_and_click 需要提供对象格式：{url, selector, timeout?}"
                selector = (args or {}).get('selector')
                url = (args or {}).get('url')
                by = (args or {}).get('by', 'css')
                timeout = int((args or {}).get('timeout', 15))
                index = (args or {}).get('index', None)
                if not selector:
                    return "❌ dom_open_and_click 需要提供 selector 参数"
                payload = {'action': 'dom_open_and_click', 'url': url, 'selector': selector, 'by': by, 'timeout': timeout}
                if index is not None:
                    payload['index'] = int(index)
                return self.controller._execute_action(payload)

            if tool in ('final_answer', 'final'):
                # Agent 自身不再调用此工具；上层将识别 tool 为 final_answer 并结束循环
                return str(args)

            return f"❌ 未知工具: {tool}"
        except Exception as e:
            return f"❌ 工具执行异常: {str(e)}"
