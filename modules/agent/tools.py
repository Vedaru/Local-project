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

from .controller import ComputerController
from .browser import WebSurfer
from ..logging_config import get_logger

logger = get_logger('AgentTools')

# 使用国内可用的搜索抓取（优先百度 https://www.baidu.com/s）
# duckduckgo 已被替换为静态爬虫方式（requests + BeautifulSoup），以适配中国大陆网络环境
import requests
from bs4 import BeautifulSoup

# ========== 已迁移的 prompt 文本（工具与 DOM 说明） ==========
DOM_EXPERT_GUIDE = '''
浏览器与 DOM 操作专家指南
- 先看后点：始终优先使用 `scan_page_elements` 获取页面元素地图，再按 id 或 selector 精准操作。
- 禁止盲点：不要在未确认页面元素时使用 index=0、不要用键盘模拟填写网页表单。
- 标准流程：dom_open -> scan_page_elements -> 读取编号地图 -> click_element_by_id 或 dom_fill。
- 网页输入须使用 dom_fill，不要使用 type_text/press_key 来填表。
- 若 scan_page_elements 未返回目标，请说明原因（动态渲染/加载延迟/隐藏元素）并建议重试或改用更宽泛的检索词。
- 搜索应使用内置 search 工具或 baidu，不要生成 google 链接。
'''

TOOL_DOCUMENTATION = '''
工具说明：
- search(query, max_results=5): 使用百度抓取，返回标题+链接+摘要的文本列表；禁止使用 Google。
- browse(url): 抓取页面并返回 title/text 摘要（适合快速阅读）。
- read_file(path): 读取工作区或绝对路径的文本文件。
- write_file(path, content): 写入文件并创建目录。
- open_local_app(app_path): 启动本地应用（仅系统级启动）。
- click_screen(x,y): 屏幕坐标点击（pyautogui）。
- dom_* 系列: dom_open, dom_query, dom_preview, dom_click, dom_fill, dom_eval, dom_status, click_element_by_id, scan_page_elements 等——优先使用 DOM API 而非键盘/鼠标模拟。
'''



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
        logger.debug(f"search() called with query={query!r}, max_results={max_results}")
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
                logger.info(f"search() no results for query={query!r}")
                return "🔍 未找到相关结果。"

            result = "\n".join(items)
            logger.debug(f"search() returning {len(items)} results for query={query!r}")
            return result
        except Exception as e:
            logger.error(f"search() error for query={query!r}: {e}", exc_info=True)
            return f"❌ 搜索错误: {str(e)}"

    # ---------------- 浏览器 ----------------
    def browse(self, url: str) -> str:
        """调用 WebSurfer.browse 并返回文本摘要（使用 requests + BeautifulSoup，适合国内环境）"""
        logger.debug(f"browse() called url={url}")
        try:
            page = self.browser.browse(url)
            text = page.get('text') if isinstance(page, dict) else str(page)
            title = page.get('title', '') if isinstance(page, dict) else ''
            snippet = (text or '')[:400].replace('\n', ' ')
            logger.debug(f"browse() success url={url} title={title}")
            return f"🔗 {title} — {url}\n{snippet}{'...' if len(text or '') > 400 else ''}"
        except Exception as e:
            logger.error(f"browse() failed url={url}: {e}", exc_info=True)
            return f"❌ 浏览失败: {str(e)}"

    # ---------------- 文件操作 ----------------
    def read_file(self, path: str) -> str:
        logger.debug(f"read_file() path={path}")
        try:
            if not os.path.exists(path):
                logger.warning(f"read_file(): file not found: {path}")
                return f"❌ 文件不存在: {path}"
            with open(path, 'r', encoding='utf-8') as f:
                data = f.read()
            logger.debug(f"read_file() success path={path} size={len(data)}")
            return data
        except Exception as e:
            logger.error(f"read_file() error path={path}: {e}", exc_info=True)
            return f"❌ 读取文件失败: {str(e)}"

    def write_file(self, path: str, content: str) -> str:
        logger.debug(f"write_file() path={path} content_len={len(content) if content is not None else 0}")
        try:
            dirp = os.path.dirname(path)
            if dirp:
                os.makedirs(dirp, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"write_file() wrote {path}")
            return f"✅ 已写入: {path}"
        except Exception as e:
            logger.error(f"write_file() failed path={path}: {e}", exc_info=True)
            return f"❌ 写入文件失败: {str(e)}"

    # ---------------- 电脑控制（包装现有 ComputerController） ----------------
    def open_local_app(self, app_path: str) -> str:
        """通过 ComputerController 执行打开应用；若 controller 不可用，尝试直接调用 pyautogui / os 启动"""
        logger.debug(f"open_local_app() app_path={app_path}")
        try:
            if self.controller:
                payload = {'action': 'open_app', 'app_path': app_path}
                logger.debug(f"open_local_app() delegating to ComputerController: {payload}")
                res = self.controller._execute_action(payload)
                logger.info(f"open_local_app() controller response: {res}")
                return res
            # 兜底：直接使用 os.startfile（仅 Windows）
            if os.name == 'nt':
                os.startfile(app_path)
                logger.info(f"open_local_app() launched directly: {app_path}")
                return f"✅ 成功启动应用（直接）：{app_path}"
            else:
                os.system(f'"{app_path}" &')
                logger.info(f"open_local_app() launched directly (non-windows): {app_path}")
                return f"✅ 成功尝试启动应用（直接）：{app_path}"
        except Exception as e:
            logger.error(f"open_local_app() failed app_path={app_path}: {e}", exc_info=True)
            return f"❌ 启动应用失败: {str(e)}"

    def click_screen(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left') -> str:
        """模拟鼠标点击（直接使用 pyautogui）"""
        logger.debug(f"click_screen() x={x} y={y} button={button}")
        try:
            if x is None or y is None:
                pyautogui.click(button=button)
            else:
                pyautogui.click(x=x, y=y, button=button)
            logger.info(f"click_screen() clicked ({x},{y}) button={button}")
            return f"✅ 点击屏幕: ({x},{y}) button={button}"
        except Exception as e:
            logger.error(f"click_screen() failed: {e}", exc_info=True)
            return f"❌ 点击失败: {str(e)}"

    # ---------------- 通用执行接口 ----------------
    def execute(self, tool: str, args: Any) -> str:
        """高层调度：将 tool 名和 args 映射到具体方法并返回字符串结果

        - 详细日志：记录入参、派发的 payload、Controller 返回及异常
        """
        logger.debug(f"execute() called tool={tool!r} args={args!r}")
        try:
            tool = (tool or '').lower()
            # 基本工具派发（各方法内部已记录详细日志）
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
                    logger.warning("write_file called with string arg (invalid)")
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

            # ------------- DOM（替代 OCR）工具（委派到 modules.agent.dom_tools） -------------
            if tool in ('dom_open','dom_navigate','dom_status','dom_fill','dom_eval','dom_query','dom_preview','dom_click','dom_open_and_click'):
                from .dom_tools import (
                    dom_open as _dom_open, dom_navigate as _dom_navigate, dom_status as _dom_status,
                    dom_fill as _dom_fill, dom_eval as _dom_eval, dom_query as _dom_query,
                    dom_preview as _dom_preview, dom_click as _dom_click, dom_open_and_click as _dom_open_and_click,
                )
                try:
                    mapper = {
                        'dom_open': _dom_open,
                        'dom_navigate': _dom_navigate,
                        'dom_status': _dom_status,
                        'dom_fill': _dom_fill,
                        'dom_eval': _dom_eval,
                        'dom_query': _dom_query,
                        'dom_preview': _dom_preview,
                        'dom_click': _dom_click,
                        'dom_open_and_click': _dom_open_and_click,
                    }
                    return mapper[tool](self.controller, args)
                except Exception as e:
                    logger.exception(f"DOM 工具执行异常: {e}")
                    return f"❌ DOM 工具异常: {e}"


            if tool in ('final_answer', 'final'):
                # Agent 自身不再调用此工具；上层将识别 tool 为 final_answer 并结束循环
                logger.debug(f"execute() final/answer called; returning args type={type(args)}")
                return str(args)

            logger.warning(f"execute() unknown tool: {tool}")
            return f"❌ 未知工具: {tool}"
        except Exception as e:
            logger.exception(f"execute() exception for tool={tool}: {e}")
            return f"❌ 工具执行异常: {str(e)}"
