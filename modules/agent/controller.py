"""
ComputerController — 将原 modules.controller.core.py 迁移到 modules.agent

此模块保存原有的指令解析与调度逻辑，供 Agent 内部直接使用。
"""

import json
import re
from typing import Tuple
from .safety import SafetyGuard
from .executor import ActionExecutor


class ComputerController:
    """
    电脑控制器类
    解析 AI 响应中的控制指令并安全执行
    """

    def __init__(self, safety_guard: SafetyGuard, action_executor: ActionExecutor):
        """
        初始化控制器

        Args:
            safety_guard: 安全守卫实例
            action_executor: 动作执行器实例
        """
        self.safety_guard = safety_guard
        self.action_executor = action_executor

    def process_command(self, response_text: str) -> Tuple[str, str]:
        """
        处理 AI 响应文本，提取并执行控制指令

        Args:
            response_text: AI 返回的完整文本（可能包含对话和指令）

        Returns:
            Tuple[str, str]: (execution_log, clean_text)
                - execution_log: 执行日志，如果无指令则为空字符串
                - clean_text: 去除指令标签后的纯对话文本
        """
        # 查找所有 [ACTION] 标签
        action_pattern = r'\[ACTION\](.*?)\[/ACTION\]'
        matches = re.findall(action_pattern, response_text, re.DOTALL)

        if not matches:
            # 无指令，返回原文本
            return "", response_text

        # 执行所有指令
        execution_logs = []
        for action_json in matches:
            try:
                action_data = json.loads(action_json.strip())

                # 验证指令格式
                if not isinstance(action_data, dict) or 'action' not in action_data:
                    execution_logs.append("❌ 指令解析失败: 缺少 'action' 字段")
                    continue

                # 执行指令
                log = self._execute_action(action_data)
                execution_logs.append(log)

            except json.JSONDecodeError as e:
                execution_logs.append(f"❌ 指令解析失败: 无效的 JSON 格式 - {str(e)}")
            except Exception as e:
                execution_logs.append(f"❌ 执行失败: {str(e)}")

        # 合并所有执行日志
        execution_log = " | ".join(execution_logs) if execution_logs else ""

        # 移除所有指令标签，获取纯对话文本
        clean_text = re.sub(action_pattern, '', response_text, flags=re.DOTALL).strip()

        return execution_log, clean_text

    def _execute_action(self, action_data: dict) -> str:
        """执行单条控制指令并返回可读的执行日志。

        支持的 action 及参数说明（摘要）：
        - open_app: {app_path}
        - type_text: {text}
        - press_key: {key}
        - save_note: {content, filename?}
        - dom_open: {url, browser_type?, headless?, browser_path?}
        - dom_navigate: {url}
        - dom_query: {selector, by?, multiple?}
        - dom_preview: {selector, by?, max_results?}
        - dom_scan: (无参数，返回页面元素地图)
          *别名*：`scan_page` （用于直接 [ACTION] 形式）
        - dom_click: {selector, by?, index?, timeout?}
        - dom_click_text: {selector, text, timeout?}
        - dom_open_and_click: {url, selector, by?, timeout?, index?}
        - dom_fill: {selector, value, by?}
        - dom_eval: {expression}
        - dom_status: (无参数)
        - dom_click_id: {id} — 基于 scan_page_elements 生成的语义 id 点击元素
          *别名*：`click_id`（直接使用）
        - dom_fill_id: {id, value} — 在语义 id 元素中输入内容
          *别名*：`fill_id`（直接使用）

        返回格式：大多数操作返回人类可读的字符串，失败以 ❌ 开头并包含简短诊断。
        注意：Agent 层会对失败响应做二次增强以提供可执行建议。
        """
        tool = action_data.get('action')

        try:
            if tool == 'open_app':
                app_path = action_data.get('app_path', '')
                if not app_path:
                    return "❌ 指令错误: open_app 缺少 'app_path' 参数"

                # 安全验证
                safe_path = self.safety_guard.validate_path(app_path)

                # 执行启动（AI 打开的窗口默认最大化）
                return self.action_executor.open_app(safe_path, maximize=True)

            elif tool == 'type_text':
                text = action_data.get('text', '')
                if not text:
                    return "❌ 指令错误: type_text 缺少 'text' 参数"

                return self.action_executor.type_text(text)

            elif tool == 'press_key':
                key = action_data.get('key', '')
                if not key:
                    return "❌ 指令错误: press_key 缺少 'key' 参数"

                return self.action_executor.press_key(key)

            elif tool == 'save_note':
                content = action_data.get('content', '')
                filename = action_data.get('filename', None)
                if not content:
                    return "❌ 指令错误: save_note 缺少 'content' 参数"

                return self.action_executor.save_note(content, filename)

            # elif tool == 'open_browser':
            #     url = action_data.get('url', None)
            #     browser_path = action_data.get('browser_path', None)
            #
            #     # `open_browser` 已移除为独立实现：优先使用 DOM（Playwright）的 `dom_open`。
            #     if getattr(self.action_executor, 'dom_available', False):
            #         return self.action_executor.dom_open(url=url, browser_path=browser_path, headless=False)
            #     return "❌ `open_browser` 已移除：请使用 `dom_open`（默认使用系统 Edge），或在无 Playwright 环境下直接调用 `webbrowser.open(url)`。"

            # 合并别名：将 `search` / `browse` 视为 `dom_open` 的语义别名（统一由 dom_open 处理）
            # elif tool in ('search', 'browse'):
            #     # 支持多种参数名：query / q / url / args / text
            #     url_or_q = (
            #         action_data.get('query') or action_data.get('q') or action_data.get('url')
            #         or action_data.get('args') or action_data.get('text')
            #     )
            #     if not url_or_q:
            #         return "❌ 指令错误: search/browse 缺少 'query'/'url' 参数"
            #     # 直接委派给 dom_open；ActionExecutor.dom_open 会把裸词转换为百度搜索 URL
            #     try:
            #         return self.action_executor.dom_open(url=url_or_q, browser_type=None, headless=False, browser_path=None)
            #     except Exception as e:
            #         return f"❌ dom_open (via search/browse) 失败: {e}"

            # ----------------- DOM（替代 OCR）指令 -----------------
            # alias for new scan_id functionality (visual mode)
            # elif tool == 'scan_page':
            #     # kept for backwards compatibility when AI uses [ACTION]{"action":"scan_page"}
            #     try:
            #         return self.action_executor.dom_scan()
            #     except Exception as e:
            #         return f"❌ scan_page 失败: {e}"

            # elif tool == 'dom_open':
            #     url = action_data.get('url', None)
            #     browser_type = action_data.get('browser_type', None)
            #     headless = bool(action_data.get('headless', False))
            #     browser_path = action_data.get('browser_path', None)
            #     return self.action_executor.dom_open(url=url, browser_type=browser_type, headless=headless, browser_path=browser_path)

            # elif tool == 'dom_navigate':
            #     url = action_data.get('url', None)
            #     if not url:
            #         return "❌ 指令错误: dom_navigate 缺少 'url' 参数"
            #     return self.action_executor.dom_navigate(url)

            # elif tool == 'dom_query':
            #     selector = action_data.get('selector', '')
            #     by = action_data.get('by', 'css')
            #     multiple = bool(action_data.get('multiple', False))
            #     if not selector:
            #         return "❌ 指令错误: dom_query 缺少 'selector' 参数"
            #     try:
            #         res = self.action_executor.dom_query(selector, by=by, multiple=multiple)
            #         return json.dumps(res, ensure_ascii=False)
            #     except Exception as e:
            #         return f"❌ dom_query 失败: {e}"

            # elif tool == 'dom_preview':
            #     selector = action_data.get('selector', '')
            #     by = action_data.get('by', 'css')
            #     max_results = int(action_data.get('max_results', 6))
            #     if not selector:
            #         return "❌ 指令错误: dom_preview 缺少 'selector' 参数"
            #     try:
            #         res = self.action_executor.dom_preview(selector, by=by, max_results=max_results)
            #         return json.dumps(res, ensure_ascii=False)
            #     except Exception as e:
            #         return f"❌ dom_preview 失败: {e}"

            # elif tool == 'dom_scan':
            #     """返回页面语义元素地图（供 LLM 阅读）。"""
            #     try:
            #         return self.action_executor.dom_scan()
            #     except Exception as e:
            #         return f"❌ dom_scan 失败: {e}"

            # elif tool == 'dom_click_id':
            #     # 按先前 scan 生成的语义 id 点击元素
            #     sid = action_data.get('id', None)
            #     if sid is None:
            #         return "❌ 指令错误: dom_click_id 缺少 'id' 参数"
            #     try:
            #         return self.action_executor.dom_click_id(int(sid))
            #     except Exception as e:
            #         return f"❌ dom_click_id 失败: {e}"

            # elif tool == 'click_id':
            #     # alias for backward compatibility: [ACTION]{"action":"click_id","id":...}
            #     sid = action_data.get('id', None)
            #     if sid is None:
            #         return "❌ 指令错误: click_id 缺少 'id' 参数"
            #     try:
            #         return self.action_executor.dom_click_id(int(sid))
            #     except Exception as e:
            #         return f"❌ click_id 失败: {e}"

            # elif tool == 'dom_click':
            #     selector = action_data.get('selector', '')
            #     by = action_data.get('by', 'css')
            #     index = action_data.get('index', None)
            #     timeout = int(action_data.get('timeout', 5))
            #     if not selector:
            #         return "❌ 指令错误: dom_click 缺少 'selector' 参数"
            #     try:
            #         if index is not None:
            #             return self.action_executor.dom_click(selector, by=by, timeout=timeout*1000, index=int(index))
            #         return self.action_executor.dom_click(selector, by=by, timeout=timeout*1000)
            #     except Exception as e:
            #         return f"❌ dom_click 失败: {e}"

            # elif tool == 'dom_click_text':
            #     selector = action_data.get('selector', '')
            #     text = action_data.get('text', '')
            #     timeout = int(action_data.get('timeout', 10))
            #     if not selector or not text:
            #         return "❌ 指令错误: dom_click_text 缺少 'selector' 或 'text' 参数"
            #     try:
            #         return self.action_executor.dom_click_text(selector, text, timeout=timeout)
            #     except Exception as e:
            #         return f"❌ dom_click_text 失败: {e}"

            # elif tool == 'dom_open_and_click':
            #     selector = action_data.get('selector', '')
            #     by = action_data.get('by', 'css')
            #     timeout = int(action_data.get('timeout', 15))
            #     url = action_data.get('url', None)
            #     index = int(action_data.get('index', 0)) if action_data.get('index') is not None else 0
            #     if not selector:
            #         return "❌ 指令错误: dom_open_and_click 缺少 'selector' 参数"
            #     try:
            #         # 将 timeout（秒）转换为毫秒再委派给 ActionExecutor.dom_open_and_click（runner 以 ms 为单位）
            #         return self.action_executor.dom_open_and_click(url=url, selector=selector, by=by, timeout=timeout * 1000, index=index)
            #     except Exception as e:
            #         return f"❌ dom_open_and_click 失败: {e}"

            # elif tool == 'dom_fill':
            #     selector = action_data.get('selector', '')
            #     value = action_data.get('value', '')
            #     by = action_data.get('by', 'css')
            #     if not selector:
            #         return "❌ 指令错误: dom_fill 缺少 'selector' 参数"
            #     return self.action_executor.dom_fill(selector, value, by=by)

            # elif tool == 'fill_id':
            #     # alias allows direct use of semantic id in [ACTION] tag
            #     sid = action_data.get('id', None)
            #     val = action_data.get('value') or action_data.get('text')
            #     if sid is None or val is None:
            #         return "❌ 指令错误: fill_id 缺少 'id' 或 'value' 参数"
            #     try:
            #         return self.action_executor.dom_fill_id(int(sid), str(val))
            #     except Exception as e:
            #         return f"❌ fill_id 失败: {e}"

            # elif tool == 'dom_eval':
            #     expr = action_data.get('expression', '')
            #     if not expr:
            #         return "❌ 指令错误: dom_eval 缺少 'expression' 参数"
            #     try:
            #         res = self.action_executor.dom_eval(expr)
            #         try:
            #             return json.dumps(res, ensure_ascii=False)
            #         except Exception:
            #             return str(res)
            #     except Exception as e:
            #         return f"❌ dom_eval 失败: {e}"

            # elif tool == 'dom_status':
            #     try:
            #         status = self.action_executor.dom_status()
            #         return json.dumps(status, ensure_ascii=False)
            #     except Exception as e:
            #         return f"❌ dom_status 失败: {e}"

            # 旧的图像/屏幕识别指令已被废弃（breaking change）
            elif tool and tool.startswith('ocr_'):
                return "❌ 已弃用：请改用对应的 dom_* 指令（例如 dom_query / dom_click / dom_open）。"

            else:
                return f"❌ 未知指令: {tool}"

        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"