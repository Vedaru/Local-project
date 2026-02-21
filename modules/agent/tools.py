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

from .controller import ComputerController
from .browser import WebSurfer
from ..logging_config import get_logger

logger = get_logger('AgentTools')

# ========== 已迁移的 prompt 文本（工具与 DOM 说明） ==========
# 以下 DOM 相关说明已弃用，代码已注释
DOM_EXPERT_GUIDE = '''
演示用：DOM 操作已弃用，相关指南暂时隐藏
'''

TOOL_DOCUMENTATION = '''
工具说明：
- read_file(path): 读取工作区或绝对路径的文本文件。
- write_file(path, content): 写入文件并创建目录。
- open_local_app(app_path): 启动本地应用。
'''



class AgentTools:
    """将若干工具以方法形式暴露给 Agent 使用。可接受已有的 ComputerController 实例。"""

    def __init__(self, controller: Optional[ComputerController] = None, browser: Optional[WebSurfer] = None):
        self.controller = controller
        # WebSurfer 使用 prefer_drission 与 timeout 参数；移除不存在的 headless 参数
        self.browser = browser or WebSurfer()

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


    # ---------------- 通用执行接口 ----------------
    def execute(self, tool: str, args: Any) -> str:
        """高层调度：将 tool 名和 args 映射到具体方法并返回字符串结果

        - 详细日志：记录入参、派发的 payload、Controller 返回及异常
        """
        logger.debug(f"execute() called tool={tool!r} args={args!r}")
        try:
            tool = (tool or '').lower()
            # 基本工具派发（各方法内部已记录详细日志）
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


            # ------------- DOM（替代 OCR）工具（委派到 modules.agent.dom_tools） -------------
            # DOM 工具路径已弃用，暂时注释并返回提示
            # if tool in ('dom_open','dom_navigate','dom_status','dom_fill','dom_eval','dom_query','dom_preview','dom_click','dom_open_and_click'):
            #     from .dom_tools import (
            #         dom_open as _dom_open, dom_navigate as _dom_navigate, dom_status as _dom_status,
            #         dom_fill as _dom_fill, dom_eval as _dom_eval, dom_query as _dom_query,
            #         dom_preview as _dom_preview, dom_click as _dom_click, dom_open_and_click as _dom_open_and_click,
            #     )
            #     try:
            #         mapper = {
            #             'dom_open': _dom_open,
            #             'dom_navigate': _dom_navigate,
            #             'dom_status': _dom_status,
            #             'dom_fill': _dom_fill,
            #             'dom_eval': _dom_eval,
            #             'dom_query': _dom_query,
            #             'dom_preview': _dom_preview,
            #             'dom_click': _dom_click,
            #             'dom_open_and_click': _dom_open_and_click,
            #         }
            #         return mapper[tool](self.controller, args)
            #     except Exception as e:
            #         logger.exception(f"DOM 工具执行异常: {e}")
            #         return f"❌ DOM 工具异常: {e}"

            # --- [新增] ID 语义操作（已弃用） ---
            # if tool == 'scan_page':
            #     return self.controller._execute_action({'action': 'dom_scan'})
            #     
            # if tool == 'click_id':
            #     # 兼容字符串或整数 ID
            #     uid = int(args) if isinstance(args, (str, int)) else int(args.get('id'))
            #     return self.controller._execute_action({'action': 'dom_click_id', 'id': uid})
            #     
            # if tool == 'fill_id':
            #     uid = int(args.get('id'))
            #     val = args.get('text') or args.get('value')
            #     return self.controller._execute_action({'action': 'dom_fill_id', 'id': uid, 'value': val})


            if tool in ('final_answer', 'final'):
                # Agent 自身不再调用此工具；上层将识别 tool 为 final_answer 并结束循环
                logger.debug(f"execute() final/answer called; returning args type={type(args)}")
                return str(args)

            logger.warning(f"execute() unknown tool: {tool}")
            return f"❌ 未知工具: {tool}"
        except Exception as e:
            logger.exception(f"execute() exception for tool={tool}: {e}")
            return f"❌ 工具执行异常: {str(e)}"
