"""
AgentTools — 为 ManusAgent 提供的工具箱包装
- 将 ComputerController / ActionExecutor 的能力以“工具”形式暴露给 Agent
- 重要约束：所有 DOM/本地操作均返回字符串（便于 Agent observation）

必须支持 LLM 常用输出名称（大小写/连字符兼容）：
- click_element_by_id
- scan_page_elements
- type_text
- press_key

实现要点：
- 优先直接调用 controller.action_executor 的方法（若存在），减小中间层出错面
- 对 controller 返回的 dict/str 做统一增强与诊断提示
"""
from typing import Optional, Any
import os
import re

import pyautogui

from modules.controller import ComputerController
from .browser import WebSurfer

import requests
from bs4 import BeautifulSoup


class AgentTools:
    """Agent 可调用的工具集包装器。

    - 所有方法应返回字符串（Agent observation-friendly）
    - 对于需要转发给 ComputerController 的操作，使用 _call_controller 统一处理
    """

    def __init__(self, controller: Optional[ComputerController] = None, browser: Optional[WebSurfer] = None):
        self.controller = controller
        self.browser = browser or WebSurfer()

    # ---------------- 基本辅助工具 ----------------
    def search(self, query: str, max_results: int = 5) -> str:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get('https://www.baidu.com/s', params={'wd': query}, headers=headers, timeout=8)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = []
            for i, div in enumerate(soup.select('div.result')[:max_results], start=1):
                title_tag = div.find('h3') or div.find('a')
                title = title_tag.get_text(strip=True) if title_tag else ''
                snippet_tag = div.find('div', class_='c-abstract') or div.find('p')
                body = snippet_tag.get_text(strip=True) if snippet_tag else ''
                items.append(f"{i}. {title}\n   {body}")
            return "\n".join(items) if items else "🔍 未找到相关结果。"
        except Exception as e:
            return f"❌ 搜索错误: {e}"

    def browse(self, url: str) -> str:
        try:
            page = self.browser.browse(url)
            text = page.get('text') if isinstance(page, dict) else str(page)
            title = page.get('title', '') if isinstance(page, dict) else ''
            snippet = (text or '')[:400].replace('\n', ' ')
            return f"🔗 {title} — {url}\n{snippet}{'...' if len(text or '')>400 else ''}"
        except Exception as e:
            return f"❌ 浏览失败: {e}"

    def read_file(self, path: str) -> str:
        try:
            if not os.path.exists(path):
                return f"❌ 文件不存在: {path}"
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"❌ 读取文件失败: {e}"

    def write_file(self, path: str, content: str) -> str:
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"✅ 已写入: {path}"
        except Exception as e:
            return f"❌ 写入文件失败: {e}"

    def open_local_app(self, app_path: str) -> str:
        try:
            if self.controller:
                return self._call_controller({'action': 'open_app', 'app_path': app_path}, tool='open_app')
            if os.name == 'nt':
                os.startfile(app_path)
                return f"✅ 成功启动应用（直接）：{app_path}"
            os.system(f'"{app_path}" &')
            return f"✅ 成功尝试启动应用（直接）：{app_path}"
        except Exception as e:
            return f"❌ 启动应用失败: {e}"

    def click_screen(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left') -> str:
        try:
            if x is None or y is None:
                pyautogui.click(button=button)
            else:
                pyautogui.click(x=x, y=y, button=button)
            return f"✅ 点击屏幕: ({x},{y}) button={button}"
        except Exception as e:
            return f"❌ 点击失败: {e}"

    # ---------------- 页面语义扫描 / id 点击（必须与 LLM 输出名称一致） ----------------
    def scan_page_elements(self) -> str:
        if not self.controller:
            return "❌ 未提供 ComputerController，无法执行 scan_page_elements"
        # 优先通过 action_executor（少一层封装）
        try:
            if hasattr(self.controller, 'action_executor') and hasattr(self.controller.action_executor, 'dom_scan'):
                return self.controller.action_executor.dom_scan()
        except Exception:
            pass
        return self._call_controller({'action': 'dom_scan'}, tool='dom_scan')

    def click_element_by_id(self, id: int) -> str:
        if not self.controller:
            return "❌ 未提供 ComputerController，无法执行 click_element_by_id"
        try:
            if hasattr(self.controller, 'action_executor') and hasattr(self.controller.action_executor, 'dom_click_id'):
                return self.controller.action_executor.dom_click_id(int(id))
        except Exception:
            pass
        return self._call_controller({'action': 'dom_click_id', 'id': int(id)}, tool='dom_click_id')

    # ---------------- Controller helpers ----------------
    def _format_controller_result(self, tool: str, res: Any, args: Any = None) -> str:
        try:
            if isinstance(res, dict):
                if res.get('ok') is True:
                    if 'text' in res and isinstance(res['text'], str):
                        return res['text']
                    if 'result' in res:
                        return res['result'] if isinstance(res['result'], str) else str(res['result'])
                    return '✅ 操作成功'
                err = res.get('error') or res.get('detail') or 'unknown error'
                base = f"❌ {tool} 失败: {err}"
                if err == 'no_page':
                    base += '；可能未调用 dom_open 或页面尚未加载完成，请先调用 dom_open 并重试。'
                if err == 'no_match':
                    base += '；未找到匹配元素，请先调用 scan_page_elements 检查元素编号或使用更宽泛的 selector。'
                return base
            if not isinstance(res, str):
                return str(res)
            s = res.strip()
            if not s.startswith('❌'):
                return s
            low = s.lower()
            if 'no_page' in low:
                return s + ' 建议：先调用 dom_open 打开页面再执行 DOM 操作。'
            if 'no_match' in low:
                return s + ' 建议：调用 scan_page_elements 检查可交互元素并使用对应 id，或尝试更宽泛的 selector。'
            if 'timeout' in low:
                return s + ' 建议：增加超时时间或检查页面是否需要更多时间加载。'
            return s + ' 建议：检查参数是否正确，或重试以获取更多信息。'
        except Exception:
            return str(res)

    def _call_controller(self, payload: dict, tool: str | None = None, args: Any = None) -> str:
        if not self.controller:
            return f"❌ 未提供 ComputerController，无法执行 {tool or payload.get('action')}"
        try:
            raw = self.controller._execute_action(payload)
            return self._format_controller_result(tool or payload.get('action'), raw, args)
        except Exception as e:
            return f"❌ 控制器调用异常: {e}"

    # ---------------- Execute 调度（对 LLM 友好） ----------------
    def execute(self, tool: str, args: Any) -> str:
        """将 LLM 提供的 tool 名映射到具体实现；支持 camelCase / snake_case / kebab-case。"""
        try:
            def _normalize(name: str) -> str:
                s = str(name or '').strip()
                s = s.replace('-', '_')
                s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', s)
                s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
                return s.lower()

            tool = _normalize(tool)

            # 基本工具
            if tool == 'search':
                q = args if isinstance(args, str) else (args or {}).get('query', '')
                return self.search(q)
            if tool == 'browse':
                url = args if isinstance(args, str) else (args or {}).get('url', '')
                return self.browse(url)
            if tool == 'read_file':
                path = args if isinstance(args, str) else (args or {}).get('path', '')
                return self.read_file(path)
            if tool == 'write_file':
                if isinstance(args, str):
                    return "❌ write_file 需要提供 path 与 content 的对象格式"
                path = (args or {}).get('path')
                content = (args or {}).get('content', '')
                return self.write_file(path, content)
            if tool == 'open_local_app':
                path = args if isinstance(args, str) else (args or {}).get('app_path')
                return self.open_local_app(path)
            if tool == 'click_screen':
                if isinstance(args, dict):
                    return self.click_screen(args.get('x'), args.get('y'), args.get('button', 'left'))
                return self.click_screen()

            # 键盘输入（优先直接调用 action_executor）
            if tool == 'type_text':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 type_text"
                text = args if isinstance(args, str) else (args or {}).get('text', '')
                if not text:
                    return "❌ type_text 需要提供 text 字符串参数"
                try:
                    if hasattr(self.controller, 'action_executor') and hasattr(self.controller.action_executor, 'type_text'):
                        return self.controller.action_executor.type_text(text)
                except Exception:
                    pass
                return self._call_controller({'action': 'type_text', 'text': text}, tool='type_text', args=args)

            if tool == 'press_key':
                if not self.controller:
                    return "❌ 未提供 ComputerController，无法执行 press_key"
                if isinstance(args, str):
                    key = args
                else:
                    key = (args or {}).get('key') or (args or {}).get('keys') or (args or {}).get('combo') or (args or {}).get('combination')
                if not key:
                    return "❌ press_key 需要提供 key/keys 参数"
                try:
                    if hasattr(self.controller, 'action_executor') and hasattr(self.controller.action_executor, 'press_key'):
                        return self.controller.action_executor.press_key(key)
                except Exception:
                    pass
                return self._call_controller({'action': 'press_key', 'key': key}, tool='press_key')

            # DOM 专用工具（与 ComputerController/ActionExecutor 协作）
            if tool == 'dom_open':
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
                return self._call_controller({'action': 'dom_open', 'url': url, 'browser_type': browser_type, 'headless': headless, 'browser_path': browser_path}, tool='dom_open')

            if tool == 'scan_page_elements':
                return self.scan_page_elements()

            if tool == 'click_element_by_id':
                sid = args if isinstance(args, (str, int)) else (args or {}).get('id')
                if sid is None:
                    return "❌ click_element_by_id 需要提供 id 参数"
                return self.click_element_by_id(int(sid))

            if tool == 'dom_navigate':
                url = args if isinstance(args, str) else (args or {}).get('url')
                if not url:
                    return "❌ dom_navigate 需要提供 url 参数"
                return self._call_controller({'action': 'dom_navigate', 'url': url}, tool='dom_navigate')

            if tool == 'dom_status':
                return self._call_controller({'action': 'dom_status'}, tool='dom_status')

            if tool == 'dom_fill':
                if isinstance(args, str):
                    return "❌ dom_fill 需要提供对象格式：{selector, value}"
                selector = (args or {}).get('selector')
                value = (args or {}).get('value', '')
                by = (args or {}).get('by', 'css')
                if not selector:
                    return "❌ dom_fill 需要提供 selector 参数"
                return self._call_controller({'action': 'dom_fill', 'selector': selector, 'value': value, 'by': by}, tool='dom_fill')

            if tool == 'dom_eval':
                expr = args if isinstance(args, str) else (args or {}).get('expression')
                if not expr:
                    return "❌ dom_eval 需要提供 expression/字符串参数"
                return self._call_controller({'action': 'dom_eval', 'expression': expr}, tool='dom_eval')

            if tool == 'dom_query':
                if isinstance(args, str):
                    selector = args
                    by = 'css'
                    multiple = False
                else:
                    selector = (args or {}).get('selector', 'body')
                    by = (args or {}).get('by', 'css')
                    multiple = bool((args or {}).get('multiple', False))
                return self._call_controller({'action': 'dom_query', 'selector': selector, 'by': by, 'multiple': multiple}, tool='dom_query')

            if tool == 'dom_preview':
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
                return self._call_controller({'action': 'dom_preview', 'selector': selector, 'by': by, 'max_results': max_results}, tool='dom_preview')

            if tool == 'dom_click':
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
                return self._call_controller(payload, tool='dom_click', args=args)

            if tool == 'dom_open_and_click':
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
                return self._call_controller(payload, tool='dom_open_and_click')

            if tool == 'dom_click_text':
                if isinstance(args, str):
                    return "❌ dom_click_text 需要提供对象格式：{selector, text, timeout?}"
                selector = (args or {}).get('selector')
                text = (args or {}).get('text') or (args or {}).get('keyword')
                timeout = int((args or {}).get('timeout', 10))
                if not selector or not text:
                    return "❌ dom_click_text 需要提供 selector 和 text 参数"
                return self._call_controller({'action': 'dom_click_text', 'selector': selector, 'text': text, 'timeout': timeout}, tool='dom_click_text')

            if tool.startswith('dom_'):
                payload = {'action': tool}
                if isinstance(args, dict):
                    payload.update(args)
                elif args is not None:
                    payload['value'] = args
                return self._call_controller(payload, tool=tool, args=args)

            if tool in ('final_answer', 'final'):
                return str(args)

            return f"❌ 未知工具: {tool}"
        except Exception as e:
            return f"❌ 工具执行异常: {e}"

