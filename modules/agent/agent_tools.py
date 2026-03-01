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

    @registry.register_tool(description="在当前页面或窗口中键入文本。如果浏览器已打开，会在浏览器页面中输入；否则向系统活跃窗口输入。")
    def type_text(self, text: str) -> str:
        """向被控制的应用或浏览器页面发送键入事件。

        优先使用 Playwright 浏览器页面输入（适合网页交互），
        如果浏览器未启动则退回到 pyautogui / PowerShell。
        """
        # 如果 Playwright 浏览器页面已打开，优先用 Playwright 键盘输入
        if getattr(self, '_page', None) is not None:
            try:
                import time
                # 确保文本输入框已聚焦再输入，否则 keyboard.type 会把文字打进空气
                try:
                    active_tag = self._page.evaluate(
                        "() => document.activeElement ? document.activeElement.tagName.toLowerCase() : ''"
                    )
                    if active_tag not in ('input', 'textarea'):
                        # 自动查找并点击第一个可见的文本/搜索输入框
                        self._page.evaluate("""
                            () => {
                                const inputs = Array.from(document.querySelectorAll(
                                    'input[type="text"], input[type="search"], input:not([type]), textarea'
                                ));
                                const visible = inputs.find(el => {
                                    const style = window.getComputedStyle(el);
                                    return el.offsetParent !== null
                                        && style.display !== 'none'
                                        && style.visibility !== 'hidden';
                                });
                                if (visible) { visible.click(); visible.focus(); }
                            }
                        """)
                        time.sleep(0.2)
                        logger.debug("type_text: 自动聚焦第一个可见输入框")
                except Exception as focus_err:
                    logger.debug(f"type_text: 自动聚焦失败（无害）: {focus_err}")
                self._page.keyboard.press("Control+a")
                import time as _t; _t.sleep(0.05)
                self._page.keyboard.type(text, delay=50)
                time.sleep(0.3)
                return f"已在浏览器页面中输入: {text}"
            except Exception as e:
                logger.warning(f"Playwright keyboard.type 失败: {e}，退回到系统级输入")
        from .tools import type_text as _type
        return _type(self, text)

    @registry.register_tool(description="按下指定按键，例如 'Enter' 或 'Ctrl+C'。如果浏览器已打开，在浏览器中按键。")
    def press_key(self, key: str) -> str:
        """发送按键事件到当前浏览器页面或系统窗体。

        优先使用 Playwright 浏览器页面按键，
        如果浏览器未启动则退回到 pyautogui。
        """
        # 如果 Playwright 浏览器页面已打开，用 Playwright 按键
        if getattr(self, '_page', None) is not None:
            try:
                import time
                self._page.keyboard.press(key)
                # 等待潜在的页面导航或新标签页（如 B站搜索会在新标签页打开）
                self._switch_to_new_tab_if_any(timeout=3.0)
                # 获取当前页面 URL 和标题，帮助 LLM 理解按键后的状态
                try:
                    url = self._page.url
                    title = self._page.title()
                    return f"已在浏览器中按下: {key}。当前页面: {title} ({url})"
                except Exception:
                    return f"已在浏览器中按下: {key}"
            except Exception as e:
                logger.warning(f"Playwright keyboard.press 失败: {e}，退回到系统级按键")
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
        """Start Playwright browser/page if not already running, or recreate if stale."""
        # Fast path: page reference exists and is still alive
        if getattr(self, '_page', None) is not None:
            try:
                self._page.url  # lightweight liveness check
                return
            except Exception:
                logger.warning("_ensure_browser: 检测到浏览器页面已失效，重新创建...")
                self._page = None
                try:
                    self._browser.close()
                except Exception:
                    pass
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._browser = None
                self._playwright = None

        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def _switch_to_new_tab_if_any(self, timeout: float = 3.0) -> bool:
        """检测是否有新标签页打开（如 B站搜索结果），如果有就切换 self._page 到新页面。

        很多网站的搜索框 form 设置了 target="_blank"，提交后结果在新标签页打开。
        Playwright 不会自动切换到新标签页，需要手动监听并切换。

        Returns: True 如果成功切换到新标签页, False 否则。
        """
        import time
        ctx = getattr(self, '_context', None)
        if ctx is None:
            # 向下兼容：如果没有 context（旧方式 browser.new_page），直接等待
            time.sleep(timeout)
            return False
        old_page = self._page
        old_pages = set(ctx.pages)
        # 等待新标签页出现，每 0.3 秒检查一次
        elapsed = 0.0
        while elapsed < timeout:
            time.sleep(0.3)
            elapsed += 0.3
            current_pages = ctx.pages
            new_pages = [p for p in current_pages if p not in old_pages]
            if new_pages:
                # 切换到最新打开的标签页
                new_page = new_pages[-1]
                try:
                    new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                self._page = new_page
                logger.info(f"检测到新标签页，已切换: {new_page.url}")
                # 关闭旧的空白页（可选，保持浏览器简洁）
                try:
                    if old_page.url in ('about:blank', 'chrome://newtab/'):
                        old_page.close()
                except Exception:
                    pass
                return True
        # 没有新标签页，可能是同页面导航，等待加载
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        return False

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
            try:
                title = self._page.title()
                return f"网页已打开: {title} ({url})。可使用 scan_page 查看页面内容。"
            except Exception:
                return f"网页已打开: {url}。可使用 scan_page 查看页面内容。"
        except Exception as e:
            logger.exception("browse() failed")
            return f"❌ 打开网页失败: {e}"

    @registry.register_tool(description="使用百度搜索指定关键词并返回搜索结果摘要。这是一个复合工具，会自动完成打开搜索页、等待结果、提取摘要的全流程。")
    def web_search(self, query: str) -> str:
        """在百度上搜索给定关键词并返回前几条结果的标题和摘要。

        参数:
            query: 搜索关键词。
        返回:
            搜索结果摘要文本。
        """
        import time
        from urllib.parse import urlencode
        logger.debug(f"web_search() query={query}")
        if not query or not query.strip():
            return "❌ 搜索关键词不能为空"
        try:
            self._ensure_browser()
            search_url = "https://www.baidu.com/s?" + urlencode({"wd": query})
            print(f"🔍 正在搜索: {query}")
            self._page.goto(search_url, wait_until="domcontentloaded")
            time.sleep(3)  # 等待搜索结果加载

            # 提取搜索结果
            results = self._page.evaluate(r"""() => {
                let items = [];
                // 百度搜索结果的常见容器
                let containers = document.querySelectorAll('.result, .c-container, .result-op');
                containers.forEach((el, i) => {
                    if (i >= 8) return;  // 最多取前8条
                    let titleEl = el.querySelector('h3, .t, .c-title');
                    let title = titleEl ? titleEl.innerText.trim() : '';
                    let abstractEl = el.querySelector('.c-abstract, .content-right_8Zs40, .c-span-last');
                    let abstract = abstractEl ? abstractEl.innerText.trim() : '';
                    if (!abstract) {
                        // 尝试获取容器内非标题的文本
                        let allText = el.innerText || '';
                        abstract = allText.replace(title, '').trim().substring(0, 200);
                    }
                    let linkEl = el.querySelector('a[href]');
                    let href = linkEl ? linkEl.href : '';
                    if (title) {
                        items.push({title: title, abstract: abstract.substring(0, 150), url: href});
                    }
                });
                return items;
            }""")

            if not results:
                # 退回到通用 scan，可能页面结构不同
                return "搜索页面已打开但未能提取结构化结果。请使用 scan_page 查看页面内容。"

            lines = [f"🔍 搜索「{query}」的结果：\n"]
            for i, r in enumerate(results, 1):
                title = r.get('title', '')
                abstract = r.get('abstract', '')
                url = r.get('url', '')
                lines.append(f"{i}. {title}")
                if abstract:
                    lines.append(f"   {abstract}")
                if url:
                    lines.append(f"   链接: {url}")
                lines.append("")
            return "\n".join(lines)

        except Exception as e:
            logger.exception("web_search() failed")
            return f"❌ 搜索失败: {e}"

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
            try:
                page_url = self._page.url
                page_title = self._page.title()
                page_info = f"当前页面: {page_title} ({page_url})\n"
            except Exception:
                page_info = ""
            elements_info = self._page.evaluate(r"""() => {
            const SKIP_TAGS = new Set(['svg','path','circle','rect','g','polygon','polyline',
                'ellipse','defs','use','symbol','clippath','mask','filter','lineargradient',
                'radialgradient','stop','pattern','line','script','style','noscript','br','hr',
                'head','html','meta','link','title','image','foreignobject','text','tspan',
                'marker','animate','animatetransform','set','desc']);
            const INTERACTIVE_TAGS = new Set(['a','button','input','select','textarea']);
            let items = [];
            let all = document.querySelectorAll('*');
            all.forEach((el, index) => {
                let tag = el.tagName.toLowerCase();
                if (SKIP_TAGS.has(tag)) return;
                // 额外检查：如果元素在 SVG 命名空间内，跳过
                if (el.namespaceURI && el.namespaceURI.includes('svg')) return;
                // 如果元素的任意祖先是 SVG，也跳过
                if (el.closest && el.closest('svg')) return;
                if (el.offsetParent === null) return;
                const isInteractive = INTERACTIVE_TAGS.has(tag)
                    || el.getAttribute('role') === 'button'
                    || el.getAttribute('role') === 'link'
                    || el.getAttribute('role') === 'tab'
                    || el.getAttribute('role') === 'menuitem'
                    || el.getAttribute('onclick') !== null;
                let text = '';
                if (isInteractive) {
                    try { text = el.innerText || ''; } catch(e) { text = ''; }
                    if (!text) text = el.value || el.getAttribute('placeholder') || '';
                    text = text.replace(/\s+/g, ' ').trim();
                    // 对交互元素也限制文本长度，避免顶层容器的聚合文本过长
                    if (text.length > 120) text = text.substring(0, 120) + '...';
                } else {
                    // 只取元素的直接文本节点，不含子元素内容，避免重复的聚合文本
                    let ownText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent)
                        .join('')
                        .replace(/\s+/g, ' ')
                        .trim();
                    if (!ownText) ownText = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                    if (!ownText) return;  // 纯容器元素无自有文本，跳过
                    text = ownText.length > 80 ? ownText.substring(0, 80) + '...' : ownText;
                }
                let href = el.getAttribute('href') || '';
                let cls = (typeof el.className === 'string') ? el.className : (el.className && el.className.baseVal || '');
                let idAttr = el.id || '';
                let placeholder = el.getAttribute('placeholder') || '';
                if (!text && !href && !cls && !idAttr) return;
                let attrs = [];
                if (href) attrs.push(`href=${href}`);
                if (cls) attrs.push(`class=${cls}`);
                if (idAttr) attrs.push(`id=${idAttr}`);
                if (placeholder && tag === 'input') attrs.push(`placeholder=${placeholder}`);
                let attrstr = attrs.length ? ` (${attrs.join(', ')})` : '';
                items.push(`[ID: el_${index}] <${tag}> ${text}${attrstr}`);
            });
            return items.slice(0, 120).join('\\n');
        }"""
            )
            return page_info + elements_info
        except Exception as e:
            logger.exception("scan_page() failed")
            return f"❌ 扫描页面失败: {e}"

    @registry.register_tool(description="在网页输入框中填入文字并按回车提交。自动定位页面中第一个可见的文本/搜索输入框，填入文本后按Enter。适合所有搜索场景，比 click_element+type_text+press_key 三步更可靠。")
    def fill_and_submit(self, text: str) -> str:
        """查找页面第一个可见输入框，清空后填入文本并按 Enter 提交。"""
        logger.debug(f"fill_and_submit() text={text}")
        if getattr(self, '_page', None) is None:
            return "浏览器未启动"
        try:
            import time
            found = self._page.evaluate("""
                () => {
                    const inputs = Array.from(document.querySelectorAll(
                        'input[type="text"], input[type="search"], input:not([type]), textarea'
                    ));
                    const visible = inputs.find(el => {
                        const style = window.getComputedStyle(el);
                        return el.offsetParent !== null
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';
                    });
                    if (!visible) return false;
                    visible.click();
                    visible.focus();
                    visible.value = '';
                    return true;
                }
            """)
            if not found:
                return "❌ 未找到可见的文本输入框"
            time.sleep(0.2)
            self._page.keyboard.press("Control+a")
            time.sleep(0.05)
            self._page.keyboard.type(text, delay=50)
            time.sleep(0.3)
            self._page.keyboard.press("Enter")
            # 等待新标签页或页面导航（B站等网站搜索会打开新标签页）
            self._switch_to_new_tab_if_any(timeout=3.0)
            try:
                url = self._page.url
                title = self._page.title()
                return f"已填入「{text}」并按Enter提交。当前页面: {title} ({url})"
            except Exception:
                return f"已填入「{text}」并按Enter提交。"
        except Exception as e:
            logger.exception("fill_and_submit() failed")
            return f"❌ fill_and_submit 失败: {e}"

    @registry.register_tool(description="根据 scan_page 输出的 id（如 el_3）、CSS class 名、或元素文本来点击页面元素。")
    def click_element(self, selector_id: str) -> str:
        """点击浏览器页面上的链接或按钮。

        selector_id 可以是：
        - scan_page 输出的 "el_3" 格式的索引
        - CSS class 名称（如 "nav-search-input"）
        - 元素的 id 属性
        - 元素中的文本内容
        """
        logger.debug(f"click_element() id={selector_id}")
        if getattr(self, '_page', None) is None:
            return "浏览器未启动"
        try:
            if "el_" in selector_id:
                # 验证 el_ 后面必须是数字，拒绝占位符如 "el_X"
                raw_index = selector_id.split('_')[1]
                if not raw_index.isdigit():
                    return f"❌ 无效的元素ID「{selector_id}」。请先用 scan_page 查看页面元素，然后使用实际的元素编号如 el_42，而不是占位符。"
                index = int(raw_index)
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
                    # 点击后可能打开新标签页（如 target="_blank" 的链接）
                    import time
                    switched = self._switch_to_new_tab_if_any(timeout=2.0)
                    if not switched:
                        # 没有新标签页，检查是否有 href 需要手动导航
                        try:
                            script_href = (
                                "() => {"
                                "\n    let all = document.querySelectorAll('*');"
                                f"\n    let el = all[{index}];"
                                "\n    let link = el.querySelector('a') || (el.tagName.toLowerCase() === 'a' ? el : null);"
                                "\n    if (!link) return '';"
                                "\n    return (link.target === '_blank' || link.target === '_new') ? link.href : '';"
                                "\n}"
                            )
                            href = self._page.evaluate(script_href)
                            if href:
                                self.browse(href)
                        except Exception as err:
                            logger.debug(f"consume href check error: {err}")
                    try:
                        url = self._page.url
                        title = self._page.title()
                        return f"已点击目标元素。当前页面: {title} ({url})"
                    except Exception:
                        return "已点击目标元素"
                else:
                    return "点击失败：索引超出范围"
            else:
                import time
                # 尝试多种选择器策略
                # 1. 尝试 CSS selector（id 属性或 class 名）
                for css_sel in [f"#{selector_id}", f".{selector_id}", f"[class*='{selector_id}']", f"input.{selector_id}", selector_id]:
                    try:
                        loc = self._page.locator(css_sel).first
                        if loc.count() > 0:
                            loc.scroll_into_view_if_needed()
                            loc.click()
                            time.sleep(0.3)
                            return f"已点击元素: {selector_id}"
                    except Exception:
                        continue
                # 2. 尝试文本匹配
                try:
                    self._page.get_by_text(selector_id).first.click()
                    time.sleep(0.3)
                    return f"已点击文本: {selector_id}"
                except Exception:
                    pass
                # 3. 尝试 placeholder 匹配
                try:
                    self._page.get_by_placeholder(selector_id).first.click()
                    time.sleep(0.3)
                    return f"已点击输入框: {selector_id}"
                except Exception:
                    pass
                return f"未找到匹配的元素: {selector_id}"
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
