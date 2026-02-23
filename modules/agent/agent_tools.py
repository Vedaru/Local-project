"""
AgentTools — 为 ManusAgent 提供的工具箱包装
- 文件读写（read_file）
- 本地电脑控制（包装现有的 ComputerController / ActionExecutor）

所有方法均返回字符串（便于在 Agent 的 Observation 中拼接与展示）。
"""
from typing import Optional, Any, Dict, Tuple
import os
import json
import re

# ComputerController 已与 AgentTools 合并，无需单独导入
# from .controller import ComputerController

from ..logging_config import get_logger

# registry is responsible for tracking tools exposed to the agent
from .registry import registry

logger = get_logger('AgentTools')

# ========== 已迁移的 prompt 文本（工具与 DOM 说明） ==========
# 以下 DOM 相关说明已弃用，代码已注释

TOOL_DOCUMENTATION = '''
工具说明：
- read_file(path): 读取工作区或绝对路径的文本文件。
- open_local_app(app_path): 启动本地应用；如果参数是 URL，将改用浏览器。
- browse(url)／navigate(url): 使用内置 Playwright 浏览器打开网页。
- scan_page(): 扫描当前浏览器页面中可交互元素的摘要列表（通常用于理解页面结构）。
- click_element(id): 点击先前 scan_page 输出中某个元素的 ID，如 "video_0" 或 "el_3"。
- type_text(text): 在当前窗口键入文本（仅当 ActionExecutor 可用时）。
- press_key(key): 按下按键（仅当 ActionExecutor 可用时）。
- save_note(content, filename): 将笔记保存到桌面。
'''


class AgentTools:
    """将若干工具以方法形式暴露给 Agent 使用。

    该类同时扮演原来的
    ``ComputerController``（指令解析与执行）的职责，因此不再
    需要单独的 controller 实例。构造函数接受安全守卫和动作
    执行器，或为了向后兼容仍然允许传入旧的 ``controller``
    对象。
    """

    def __init__(
        self,
        controller: Optional[Any] = None,
        safety_guard: Optional[Any] = None,
        # ``action_executor`` 参数已不再推荐使用；AgentTools 会在内部根据
        # ``safety_guard`` 自动创建所需的执行器。如果你传入了一个实例，
        # 它仍会被接收以保持兼容，但将来可能会删除此参数。
        action_executor: Optional[Any] = None,
        executor_failsafe: bool = True,  # used when AgentTools instantiates its own executor
    ):
        # 优先使用传入的 controller（向后兼容）
        if controller is not None:
            # 将旧的 ComputerController 拆解
            self.safety_guard = controller.safety_guard
            self.action_executor = controller.action_executor
        else:
            self.safety_guard = safety_guard
            # legacy compatibility: some external code may still expect
        # `agent_tools.action_executor` attribute, but we no longer create
        # or require an ActionExecutor instance.  The standalone helper
        # functions in `tools` now implement all needed behavior directly.
        self.action_executor = None

        # Note: we used to auto-instantiate an ActionExecutor here if one
        # wasn't provided.  That class has been deprecated and may be
        # removed entirely; tools will work without it.



        # 浏览器相关状态。我们将在需要时懒初始化 Playwright
        self._playwright = None
        self._browser = None
        self._page = None

    # ---------------- 指令解析与执行（原 ComputerController 方法） ----------------
    @registry.register_tool(description="解析 LLM 回复中的命令并交给底层工具处理。返回 (动作, 参数) 二元组。")
    def process_command(self, response_text: str) -> Tuple[str, str]:
        """接受 LLM 的原始文本回复，调用内部的 `tools.process_command`。

        该工具并不直接由 Agent 在循环里使用，而是给外部组件做
        解析辅助时调用。

        参数:
            response_text: LLM 输出的原始字符串。
        返回:
            二元组 (action, args) 表示解析出的命令。
        """
        from .tools import process_command as _proc
        return _proc(self, response_text)

    # internal helpers are not registered as tools, but we keep the
    # method for backwards compatibility with existing callers.
    def _execute_action(self, action_data: dict) -> str:
        """Execute a single action descriptor.

        该方法仍保留以支持旧有流程，但它不会出现在工具列表中。
        """
        tool = action_data.get('action')
        if tool == 'open_local_app':
            app_path = action_data.get('app_path', '')
            return self.open_local_app(app_path)
        elif tool == 'open_app':  # alias sometimes used by older prompts
            app_path = action_data.get('app_path', '')
            return self.open_local_app(app_path)
        elif tool == 'type_text':
            text = action_data.get('text', '')
            return self.type_text(text)
        elif tool == 'press_key':
            key = action_data.get('key', '')
            return self.press_key(key)
        elif tool == 'save_note':
            content = action_data.get('content', '')
            filename = action_data.get('filename', None)
            return self.save_note(content, filename)
        elif tool == 'browse':
            url = action_data.get('url', '')
            return self.browse(url)
        elif tool == 'scan_page':
            return self.scan_page()
        elif tool == 'click_element':
            element_id = action_data.get('id') or action_data.get('element_id') or ''
            return self.click_element(element_id)
        else:
            return f"❌ 未知指令: {tool}"

    # ---------------- convenience helpers (previously on ActionExecutor) ----------------
    @registry.register_tool(description="对路径进行安全校验，如由安全守卫提供。")
    def validate_path(self, path: str) -> str:
        """将给定路径转交给安全守卫处理。

        如果没有配置安全守卫会原样返回。
        """
        if self.safety_guard:
            return self.safety_guard.validate_path(path)
        return path

    @registry.register_tool(description="在当前活跃窗口键入文本。")
    def type_text(self, text: str) -> str:
        """向被控制的应用发送键入事件。

        工具实现现在不依赖任何单独的执行器类；直接使用底层
        库（例如 `pyautogui` 或 PowerShell）完成操作。
        """
        from .tools import type_text as _type
        return _type(self, text)

    @registry.register_tool(description="按下指定按键，例如 'Enter' 或 'Ctrl+C'。")
    def press_key(self, key: str) -> str:
        """发送按键事件到当前窗体。

        与 `type_text` 相同，该功能现在由 `tools` 中的实现完成，
        无需额外执行器。
        """
        from .tools import press_key as _press
        return _press(self, key)

    @registry.register_tool(description="将文本保存到桌面，适用于记事或日志。")
    def save_note(self, content: str, filename: str = None) -> str:
        """把给定文本写入桌面上的文件。

        参数:
            content: 要保存的文字。
            filename: 可选的文件名，若未提供会让系统自动生成。
        """
        from .tools import save_note_to_desktop as _save
        return _save(content, filename)

    def ensure_playwright(self) -> bool:
        """内部辅助：确保 Playwright 浏览器准备就绪。

        我们不再通过 `ActionExecutor` 驱动，这个方法尽可能简单。
        """
        try:
            # lazy import just to see if playwright is available
            from playwright.sync_api import sync_playwright  # type: ignore
            return True
        except Exception:
            return False


    @property
    def dom_available(self) -> bool:
        """Convenience property exposing whether DOM/browser control is ready.

        Previously this reflected the executor state; now it simply checks
        if our internal browser page has been created.
        """
        return getattr(self, '_page', None) is not None


    # ---------------- 文件操作 ----------------
    @registry.register_tool(description="读取指定文件的内容并返回文本字符串。")
    def read_file(self, path: str) -> str:
        """读取工作区或绝对路径的文本文件。

        参数:
            path: 文件路径。
        返回:
            文件内容的字符串。
        """
        from .tools import read_file as _read
        return _read(path)


    # ---------------- 电脑控制相关逻辑 ----------------
    @registry.register_tool(description="启动本地应用或在浏览器中打开 URL。")
    def open_local_app(self, app_path: str) -> str:
        """传递给底层的 open_local_app 工具。

        如果参数是 URL，会尝试通过浏览器打开。
        """
        from .tools import open_local_app as _open
        return _open(self, app_path)

    # ---------------- 浏览器/DOM 工具 ----------------
    # 以下方法直接实现原 WebSurfer 功能，以便将 browser.py 移除。

    def _ensure_browser(self) -> None:
        """Start Playwright browser/page if not already running."""
        if getattr(self, '_page', None) is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=False)
            self._page = self._browser.new_page()

    @registry.register_tool(description="使用 Playwright 在无头浏览器中打开页面并返回状态信息。")
    def browse(self, url: str) -> str:
        """访问网页并返回结果消息。

        如果 Playwright 浏览器尚未启动会进行懒初始化。
        """
        logger.debug(f"browse() url={url}")
        try:
            self._ensure_browser()
            print(f"🌐 正在访问: {url}")
            self._page.goto(url, wait_until="domcontentloaded")
            import time; time.sleep(2)
            return "网页已打开。"
        except Exception as e:
            logger.exception("browse() failed")
            return f"❌ 打开网页失败: {e}"

    @registry.register_tool(description="列出当前浏览器页面中的所有可见元素并显示标签、文本和相关属性。返回最多50条信息。")
    # NOTE: we permit an optional unused argument so that LLM may
    # accidentally supply a descriptive string without causing a crash.
    def scan_page(self, _arg: str = None) -> str:
        """获取当前页面的元素列表。

        为了提供更广泛的视野，该工具现在遍历页面的所有元素
        (`querySelectorAll('*')`)，但只保留“可见的”节点（`offsetParent`
        非空）。每项包含：
        - HTML 标签名
        - 元素文本或 `aria-label`/`title`
        - 常见属性如 `href`、`class`、`id` 等
        - 以 `[ID: el_n]` 格式编号便于引用

        只返回最多 50 条，以避免过长。
        """
        logger.debug("scan_page()")
        if getattr(self, '_page', None) is None:
            return "浏览器未启动"
        try:
            elements_info = self._page.evaluate(r"""() => {
            let items = [];
            let all = document.querySelectorAll('*');
            all.forEach((el, index) => {
                if (el.offsetParent === null) return;
                let text = '';
                try {
                    text = el.innerText || '';
                } catch (e) {
                    text = '';
                }
                text = text.replace(/\s+/g, ' ').trim();
                if (text.length <= 1) text = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                let tag = el.tagName.toLowerCase();
                let href = el.getAttribute('href') || '';
                let cls = el.className || '';
                let idAttr = el.id || '';
                // skip nodes with no text and no meaningful attributes
                if (!text && !href && !cls && !idAttr) return;
                let attrs = [];
                if (href) attrs.push(`href=${href}`);
                if (cls) attrs.push(`class=${cls}`);
                if (idAttr) attrs.push(`id=${idAttr}`);
                let attrstr = attrs.length ? ` (${attrs.join(', ')})` : '';
                items.push(`[ID: el_${index}] <${tag}> ${text}${attrstr}`);
            });
            return items.slice(0, 50).join('\\n');
        }"""
            )
            return elements_info
        except Exception as e:
            logger.exception("scan_page() failed")
            return f"❌ 扫描页面失败: {e}"

    @registry.register_tool(description="根据上一次 scan_page 输出的 id 点击页面元素。")
    def click_element(self, selector_id: str) -> str:
        """点击浏览器页面上的链接或按钮。

        selector_id 通常由 `scan_page` 输出，例如 "el_3"。
        """
        logger.debug(f"click_element() id={selector_id}")
        if getattr(self, '_page', None) is None:
            return "浏览器未启动"
        try:
            if "el_" in selector_id:
                index = int(selector_id.split('_')[1])
                # click the nth element in the same ordering used by scan_page
                script = f"""() => {{
                    let all = document.querySelectorAll('*');
                    if (all.length <= {index}) return false;
                    let el = all[{index}];
                    el.scrollIntoView({{behavior:'auto', block:'center'}});
                    // if this element contains an <a> descendant, prefer clicking that
                    let link = el.querySelector('a');
                    if (link) {{
                        link.click();
                    }} else {{
                        el.click();
                    }}
                    return true;
                }}"""
                clicked = self._page.evaluate(script)
                if clicked:
                    # additional check: if element was a link opening new tab, attempt to navigate
                    try:
                        # build script without f-string to avoid brace escapes
                        script_href = (
                            "() => {"  # opening for arrow function
                            "\n    let all = document.querySelectorAll('*');"
                            f"\n    let el = all[{index}];"
                            "\n    let link = el.querySelector('a');"
                            "\n    return link ? link.href : '';"
                            "\n}"
                        )
                        href = self._page.evaluate(script_href)
                        if href:
                            # if target is _blank the click may not change our page, so browse manually
                            self.browse(href)
                    except Exception as err:
                        logger.debug(f"consume href check error: {err}")
                    return "已点击目标元素"
                else:
                    return "点击失败：索引超出范围"
            else:
                self._page.get_by_text(selector_id).first.click()
                return f"已尝试点击文本: {selector_id}"
        except Exception as e:
            return f"点击失败: {e}"

    @registry.register_tool(description="向 Agent 返回最终结果，通常结束执行循环。")
    def final_answer(self, content) -> str:
        """把任意对象转换为字符串，作为最终输出传给 Agent。"""
        return str(content)

    # ---------------- 通用执行接口 ----------------
    def execute(self, tool: str, args: Any) -> str:
        """通用分发入口。

        新实现交由 ``registry`` 处理，避免手工维护大量 if/else。
        """
        try:
            return registry.dispatch_tool(tool, args, instance=self)
        except KeyError:
            logger.warning(f"execute() unknown tool: {tool}")
            return f"❌ 未知工具: {tool}"
