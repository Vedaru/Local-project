"""
执行模块 - PyAutoGUI 封装（从 modules.controller.executor 迁移到 modules.agent）

此模块负责实际执行电脑控制操作（启动应用、键盘输入、Playwright DOM 操作等）。
保留原有实现以确保行为一致。为了减少单文件体积，Playwright runner 与 DOM 辅助函数
已被拆分到 `playwright_runner.py` 与 `dom_utils.py`，但该文件仍保留核心调用逻辑以兼容现有 API。
"""

import subprocess
import os
import time
import json
import re
import pyautogui
import numpy as np
from typing import Optional
from ..logging_config import get_logger

logger = get_logger('ActionExecutor')


class ActionExecutor:
    """
    动作执行器类（已移除 Tesseract OCR 相关实现）

    说明：项目已弃用基于 Tesseract 的 OCR，改用 DOM（Playwright）进行网页交互与元素定位。
    本类保留旧的 API 以兼容上层调用，但 `ocr_available` 始终为 False。
    """

    def __init__(self, failsafe: bool = True):
        """
        初始化执行器（已移除 OCR 初始化逻辑）。

        Args:
            failsafe: 是否开启 PyAutoGUI 防故障机制
        """
        pyautogui.FAILSAFE = failsafe
        self.failsafe = failsafe

        # 已移除旧的屏幕识别逻辑；统一使用 DOM（Playwright）替代
        self.ocr_available = False
        self.force_disable_ocr = True
        logger.info('已移除旧的屏幕识别逻辑；改用 DOM/Playwright。')

        # ——— 用户已选择放弃 OCR：强制禁用 OCR，改用 DOM (Playwright) 进行网页交互 ———
        try:
            # 强制禁用旧的屏幕识别标记（全局）
            self.force_disable_ocr = True
            self.ocr_available = False
            logger.info('已禁用屏幕识别（改用 DOM）。')

            # Playwright 将采用后台 asyncio 线程运行以避免 greenlet / 线程切换错误（惰性初始化）
            self.dom_available = False
            self._pw = None            # 保留兼容字段（诊断）
            self._pw_runner = None     # 后台 runner（线程安全）

            try:
                # 仅检测包是否存在，实际初始化由 _ensure_playwright 完成（惰性）
                import playwright  # type: ignore
                logger.info('Playwright 包已检测（惰性初始化）。')
            except Exception as e:
                logger.warning(f'Playwright 未安装或不可用: {e}（如需 DOM，请安装 playwright 并运行 playwright install）')
                self.dom_available = False
        except Exception:
            # 若上面任何一步失败，不影响其余功能
            self.dom_available = False


    def open_app(self, path: str, maximize: bool = False) -> str:
        """
        启动应用程序并（可选）将其最大化

        Args:
            path: 应用绝对路径
            maximize: 是否在启动后最大化新窗口（AI 调用时建议为 True）

        Returns:
            str: 执行结果日志
        """
        try:
            logger.info(f"正在尝试启动应用: {path} (maximize={maximize})")

            # 记录启动前窗口标题，用于识别新窗口
            before_titles = self._capture_window_titles()

            if os.name == 'nt':
                os.startfile(path)
            else:
                subprocess.Popen([path], shell=False)

            # 等待并尝试最大化新窗口
            if maximize:
                maxed = self._maximize_new_windows(before_titles, title_hint=os.path.basename(path))
                logger.info(f"open_app: 最大化窗口数量={maxed}")

            # 屏幕识别功能已弃用（项目改用 DOM / Playwright），不再尝试刷新相关语言包
            # ...existing code...
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
        """保存笔记（委派到 modules.agent.file_tools.save_note_to_desktop）。"""
        try:
            from .file_tools import save_note_to_desktop
            return save_note_to_desktop(content, filename)
        except Exception as e:
            return f"❌ 保存笔记失败, 错误: {e}"


    # ----------------- 窗口管理工具 -----------------
    def _capture_window_titles(self):
        """委派到 `modules.agent.window.capture_window_titles`。"""
        try:
            from .window import capture_window_titles
            return capture_window_titles()
        except Exception:
            return set()

    def _maximize_new_windows(self, before_titles: set, title_hint: str = None, timeout: float = 3.0) -> int:
        """委派到 `modules.agent.window.maximize_new_windows`。"""
        try:
            from .window import maximize_new_windows
            return maximize_new_windows(before_titles, title_hint=title_hint, timeout=timeout)
        except Exception:
            return 0

    # ---- 已删除: refresh_ocr ----
    # 项目已弃用 OCR；refresh_ocr 的实现已移除。
    # 如需检测网页内容，请使用 DOM 接口（dom_open / dom_query / dom_click / dom_status）。

    # ---- 已删除: open_browser ----
    # `open_browser` 已移除。请使用 `dom_open`（Playwright）进行网页/浏览器交互。
    # 若需要在没有 Playwright 的环境中打开系统浏览器，请在上层调用 `webbrowser.open(...)`。

    # ---- 已删除: find_text_on_screen ----
    # OCR 功能已弃用；如需查找网页元素请使用 DOM 接口（dom_query / dom_click / dom_status）。


    # ----------------- DOM（Playwright）网页操作 -----------------
    # PlaywrightRunner 已抽取为 `modules.agent.playwright_runner.PlaywrightRunner`，
    # 嵌套实现已移除以减小此文件体积；executor 通过 `_ensure_playwright()` 惰性导入并使用外部 runner。
    def _ensure_playwright(self) -> bool:
        """确保 Playwright 后台 runner 已启动并可用（线程安全）。"""
        # fast path: already available
        if getattr(self, 'dom_available', False) and getattr(self, '_pw_runner', None):
            return True
        try:
            # ensure package exists
            try:
                from playwright.async_api import async_playwright  # noqa: F401
            except Exception as ie:
                logger.warning(f'Playwright 包不可用: {ie}')
                self.dom_available = False
                return False

            # start runner if not there
            if not getattr(self, '_pw_runner', None):
                try:
                    from .playwright_runner import PlaywrightRunner as _ExternalPlaywrightRunner
                    self._pw_runner = _ExternalPlaywrightRunner()
                except Exception:
                    self._pw_runner = self._PlaywrightRunner() if hasattr(self, '_PlaywrightRunner') else None

            # check startup flag
            if not getattr(self._pw_runner, 'started', None) or not self._pw_runner.started.is_set():
                logger.warning('Playwright runner 无法启动或超时。')
                self.dom_available = False
                return False

            self.dom_available = True
            logger.info('Playwright runner 已启动（线程安全）。')
            return True
        except Exception as e:
            logger.warning(f'Playwright 初始化失败: {e}')
            self.dom_available = False
            return False

    def _auto_recover_page(self):
        """如果页面不存在，自动打开一个空白页或百度。

        发生 no_page 错误时调用它可以避免后续操作因为空页面失败。
        """
        # runner 可能为 None 或尚未初始化
        runner = getattr(self, '_pw_runner', None)
        if not runner:
            return False
        page_attr = getattr(runner, '_page', None)
        if not page_attr:
            logger.warning("检测到页面丢失 (no_page)，正在尝试自动恢复...")
            # 默认打开一个常见的页面，避免 AI 对空气操作
            try:
                self.dom_open("https://www.baidu.com")
                # 给一点时间让页加载
                import time
                time.sleep(2)
                return True
            except Exception:
                return False
        return False

    def dom_open(self, url: str = None, browser_type: str = None, headless: bool = False, browser_path: str = None) -> str:
        """使用 Playwright 打开浏览器并导航（线程安全）。"""
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_open"
        if not self._ensure_playwright():
            return "❌ DOM 操作不可用：Playwright 未安装或初始化失败。请执行 `pip install playwright` 并运行 `playwright install`。"
        try:
            # 支持传入 'edge' / 'msedge' 作为别名；若未显式指定 browser_type，则默认使用系统的 Microsoft Edge（Playwright 使用 Chromium 引擎 + edge 可执行文件）。
            import shutil

            exec_path = browser_path
            if not browser_type:
                bt = 'chromium'  # Playwright 引擎
                # 尝试寻找本机 Edge 可执行文件（Windows 常见路径 / PATH）
                if not exec_path:
                    exec_path = shutil.which('msedge') or shutil.which('MicrosoftEdge')
                    if not exec_path:
                        candidates = [
                            r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                            r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                        ]
                        for p in candidates:
                            if os.path.exists(p):
                                exec_path = p
                                break
            else:
                bt = browser_type.lower()
                if bt in ('edge', 'msedge'):
                    bt = 'chromium'
                    if not exec_path:
                        exec_path = shutil.which('msedge')
                # 保持传入的 browser_path 优先

            if bt not in ('chromium', 'firefox', 'webkit'):
                return f"❌ 不支持的 browser_type: {bt}"

            res = self._pw_runner.open(bt, url, headless, exec_path)
            if res.get('ok'):
                final_url = res.get('url') or url
                norm = self._canonical_search_url(final_url) if final_url else final_url
                logger.info(f"dom_open: 打开 {bt} 成功, url={final_url}")
                used = f" ({'Edge' if exec_path and 'msedge' in (exec_path or '').lower() else bt})"
                return f"✅ DOM 浏览器已启动{used} 并导航到: {norm or (final_url or 'about:blank')}"
            else:
                return f"❌ dom_open 失败: {res.get('error', 'unknown')}"
        except Exception as e:
            logger.error(f"dom_open 失败: {e}", exc_info=True)
            return f"❌ dom_open 失败: {e}"

    def dom_navigate(self, url: str, timeout: int = 15000) -> str:
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_navigate"
        # 🔥 ensure runner exists
        if not self._ensure_playwright() or not getattr(self, '_pw_runner', None):
            return "❌ dom_navigate 失败: Playwright 服务未启动"
        try:
            res = self._pw_runner.navigate(url, timeout)
            if res.get('ok'):
                return f"✅ 已导航到: {url}"
            return f"❌ 导航失败: {res.get('error')}"
        except Exception as e:
            return f"❌ 导航失败: {e}"

    def dom_query(self, selector: str, by: str = 'css', multiple: bool = False, timeout: int = 5000):
        # DEPRECATED: DOM operations disabled
        return []
        # 🔥 ensure runner exists
        if not self._ensure_playwright() or not getattr(self, '_pw_runner', None):
            return []
        # 自动恢复页面若丢失
        self._auto_recover_page()
        try:
            results = self._pw_runner.query(selector, by=by, multiple=multiple)
            # 清洗 attributes，避免把裸数字 id（如 HTML id="163"）等直接返回给 LLM
            for it in (results or []):
                attrs = it.get('attributes')
                if isinstance(attrs, dict):
                    clean_attrs = {}
                    for k, v in attrs.items():
                        k_low = (k or '').lower()
                        # 不泄露原始元素 id 或扫描本地 id
                        if k_low in ('id', 'data-seeka-id', 'data-seekaid'):
                            continue
                        # 避免返回纯数字值（可能会误导 LLM）
                        if isinstance(v, str) and re.fullmatch(r"\s*\d{2,}\s*", v):
                            continue
                        clean_attrs[k] = v
                    it['attributes'] = clean_attrs
            return results
        except Exception as e:
            logger.error(f"dom_query 失败: {e}", exc_info=True)
            return []

    def dom_preview(self, selector: str, by: str = 'css', max_results: int = 6, timeout: int = 5000):
        """列出匹配 selector 的候选元素（用于让用户/Agent 先确认再点击）。
        # DEPRECATED: DOM operations disabled
        return []

        返回：候选元素列表（每项包含 index, text, attributes, box, summary）。不执行点击。
        """
        try:
            items = self.dom_query(selector, by=by, multiple=True, timeout=timeout)
            if not items:
                return []

            preview = []
            for i, it in enumerate(items[:max_results]):
                text = (it.get('text') or '').strip()
                href = (it.get('attributes') or {}).get('href') or (it.get('attributes') or {}).get('data-target-url')
                summary = text or href or it.get('innerHTML','')[:120]
                # 清洗 attributes，去除可能误导 LLM 的裸数字 id 或扫描本地 id
                raw_attrs = it.get('attributes', {}) or {}
                clean_attrs = {}
                for ak, av in raw_attrs.items():
                    ak_low = (ak or '').lower()
                    if ak_low in ('id', 'data-seeka-id', 'data-seekaid'):
                        continue
                    if isinstance(av, str) and re.fullmatch(r"\s*\d{2,}\s*", av):
                        continue
                    clean_attrs[ak] = av

                preview.append({
                    'index': i,
                    'text': text,
                    'href': href,
                    'attributes': clean_attrs,
                    'box': it.get('box', {}),
                    'summary': summary[:240]
                })
            return preview
        except Exception as e:
            logger.error(f"dom_preview 失败: {e}", exc_info=True)
            return []

    def dom_click(self, selector: str, by: str = 'css', timeout: int = 5000, index: Optional[int] = None) -> str:
        """在 DOM 页面上点击元素 — **仅使用回退策略**（query -> click_index / 候选 selector）。
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_click"

        首先尝试自动恢复页面以避免 no_page 情况。
        根据你的要求，删除了对 locator.click 的直接尝试，始终通过查询匹配集合并按索引点击
        （更稳定、可控）。
        """
        # 避免空页面导致操作失败
        self._auto_recover_page()

        # 安全检查：如果页面上没有任何非空 input/textarea 值，则可能 AI 未输入文本
        try:
            has_filled = self._pw_runner.evaluate(
                "() => Array.from(document.querySelectorAll('input,textarea')).some(e=>e.value && e.value.trim().length>0)"
            )
            if not has_filled:
                logger.warning("页面上没有检测到输入内容，点击可能是误操作")
                return "❌ dom_click 失败: 页面没有输入内容，避免误触"
        except Exception:
            # ignore evaluation errors
            pass

        if not getattr(self, '_pw_runner', None):
            return "❌ DOM runner 未初始化。"

        try:
            # 只使用回退策略：构建候选 selector 列表并按顺序尝试
            candidates = [selector]
            if "href^=\"https://www.bilibili.com/video/\"" in selector or "href^=\'https://www.bilibili.com/video/\'" in selector:
                candidates += [
                    "a[href^=\'/video/']",
                    "a[href*='/video/']",
                    "a[class*='bili-video-card__image--link']",
                    "a.bili-video-card__image--link",
                ]
            else:
                candidates += [
                    "a[href*='/video/']",
                    "a[class*='bili-video-card__image--link']",
                    "a.bili-video-card__image--link",
                ]

            tried = set()
            last_err = None
            for cand in candidates:
                if cand in tried:
                    continue
                tried.add(cand)
                try:
                    handles = self._pw_runner.query(cand, by='css', multiple=True)
                    if not handles:
                        continue
                    idx = int(index) if index is not None else 0
                    res = self._pw_runner.click_index(cand, by='css', index=idx, timeout=timeout)
                    if res.get('ok'):
                        return f"✅ dom_click（回退-only）已点击: {cand} (index={idx})"
                    last_err = res.get('detail') or res.get('error') or 'unknown'
                    logger.debug(f"dom_click candidate failure: selector={cand} index={idx} error={last_err}")
                except Exception as e:
                    last_err = str(e)
                    logger.debug(f"dom_click candidate exception: selector={cand} index={idx} exc={last_err}")
                    continue

            return f"❌ dom_click（回退-only）失败: {last_err or '未匹配到任何元素'}"
        except Exception as e:
            logger.error(f"dom_click 捕获到未处理异常: {e}", exc_info=True)
            return f"❌ dom_click 失败: {e}"

    def dom_fill(self, selector: str, value: str, by: str = 'css') -> str:
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_fill"
        # 🔥 ensure runner exists
        if not self._ensure_playwright() or not getattr(self, '_pw_runner', None):
            return "❌ dom_fill 失败: Playwright 服务未启动"
        # 自动恢复页面若丢失
        self._auto_recover_page()
        try:
            res = self._pw_runner.fill(selector, value, by=by)
            if res.get('ok'):
                return f"✅ 已填入文本到 {selector}"
            return f"❌ dom_fill 失败: {res.get('error')}"
        except Exception as e:
            logger.error(f"dom_fill 失败: {e}", exc_info=True)
            return f"❌ dom_fill 失败: {e}"

    def dom_search(self, selector: str, value: str):
        """原子化搜索：输入并立即回车
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_search"

        新增 URL 直达拦截：
        - B 站导航条搜索框 `.nav-search-input` -> 直接打开拼接结果页
        - 百度 `#kw` 输入框 -> 同理构造百度搜索 URL
        其他情况沿用原有填表+回车逻辑。
        """
        if not self._ensure_playwright():
            return "❌ 浏览器未启动"

        # 先尝试识别常见站点并使用 URL 跳转
        try:
            if 'nav-search-input' in selector:
                # Bilibili 搜索直接构造结果页
                url = f"https://search.bilibili.com/all?keyword={value}"
                logger.info(f"dom_search intercepted B站搜索，直接 open URL: {url}")
                return self.execute('dom_open', url)
            if '#kw' in selector or 'kw' in selector:
                # 百度搜索框
                url = f"https://www.baidu.com/s?wd={value}"
                logger.info(f"dom_search intercepted 百度搜索，直接 open URL: {url}")
                return self.execute('dom_open', url)
        except Exception as e:
            logger.warning(f"dom_search URL 拦截失败: {e}")
            # 如果出现异常，回退到正常流程

        try:
            # 1. 调用刚才优化过的 fill
            res = self._pw_runner.fill(selector, value)
            if not res.get('ok'):
                return f"❌ 输入失败: {res.get('error')}"

            # 2. 再次校验值 (防止被B站自动改回推荐词)
            # 这是一个同步方法，需要在 runner 里加一个 input_value 的包装，或者直接用 evaluate
            tmp = self._pw_runner.evaluate(f"document.querySelector('{selector}').value")
            check_val = tmp.get('result') if isinstance(tmp, dict) and 'result' in tmp else tmp

            if check_val != value:
                # 最后的挣扎：JS 强行搜索
                logger.warning(f"值仍不匹配: {check_val} != {value}，尝试 JS 提交")
                # 这种写法是直接修改 location，最稳
                # 但为了保持 Agent 逻辑，我们还是尝试再次 JS 注入并回车
                js_force = f"""
                    let input = document.querySelector('{selector}');
                    input.value = '{value}';
                    input.dispatchEvent(new Event('input', {{bubbles:true}}));
                    // 找到旁边的搜索按钮点击
                    let btn = document.querySelector('.nav-search-btn');
                    if(btn) btn.click();
                """
                self._pw_runner.evaluate(js_force)
                return f"✅ 已通过 JS 强制提交搜索: {value}"

            # 3. 正常回车
            self._pw_runner.evaluate(f"document.querySelector('{selector}').focus()")
            self._pw_runner._run(self._pw_runner._page.keyboard.press('Enter'))

            return f"✅ 搜索指令已发送: {value}"

        except Exception as e:
            return f"❌ 搜索崩溃: {e}"

    def dom_eval(self, expression: str):
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_eval"
        # 🔥【新增】确保 Runner 已初始化
        if not self._ensure_playwright() or not getattr(self, '_pw_runner', None):
            return "❌ dom_eval 失败: Playwright 服务未启动"

        # 自动恢复页面若丢失
        self._auto_recover_page()
        # 预检查：若表达式使用 querySelector 访问元素，先确认 selector 存在
        try:
            import re, json
            m = re.search(r"querySelector\(['\"](.*?)['\"]\)", expression)
            if m:
                sel = m.group(1)
                exists = self._pw_runner.evaluate(f"() => !!document.querySelector({json.dumps(sel)})")
                if not exists:
                    return f"❌ dom_eval 失败: 选择器 {sel} 未匹配到任何元素"
        except Exception:
            # 预检查失败不影响正常流程
            pass
        try:
            # 这里的 _pw_runner 此时一定不是 None
            res = self._pw_runner.evaluate(expression)
            if isinstance(res, dict) and not res.get('ok', True):
                err = res.get('error')
                detail = res.get('detail')
                logger.error(f"dom_eval 错误: {err}, 详情: {detail}")
                if detail:
                    return f"❌ dom_eval 失败: {err}: {detail}"
                return f"❌ dom_eval 失败: {err}"
            return res.get('result') if isinstance(res, dict) and 'result' in res else res
        except Exception as e:
            # 额外在日志中记录表达式本身，方便排查
            logger.error(f"dom_eval 异常: {e} (expr={expression})", exc_info=True)
            return f"❌ dom_eval 失败: {e}"

    def _canonical_search_url(self, url: str | None) -> str | None:
        """若 URL 为搜索页面或裸词，返回规范化的百度搜索 URL（https://www.baidu.com/s?wd=...），否则返回原 URL。"""
        try:
            if not url:
                return None
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
            p = urlparse(url)
            # 裸词 -> 转为百度搜索
            if not p.scheme or not p.netloc:
                return 'https://www.baidu.com/s?' + urlencode({'wd': url})
            hostname = (p.hostname or '').lower()
            path = p.path or ''
            if 'google.' in hostname and path.startswith('/search'):
                qs = parse_qs(p.query)
                qval = qs.get('q', [''])[0]
                return 'https://www.baidu.com/s?' + urlencode({'wd': qval}) if qval else 'https://www.baidu.com'
            if 'bing.com' in hostname:
                qs = parse_qs(p.query)
                qval = qs.get('q', [''])[0] if 'q' in qs else None
                if qval:
                    return 'https://www.baidu.com/s?' + urlencode({'wd': qval})
            return url
        except Exception:
            return url

    def dom_status(self) -> dict:
        # DEPRECATED: DOM operations disabled
        return {'dom_available': False, 'has_page': False, 'current_url': None}
        # ensure runner
        if not self._ensure_playwright() or not getattr(self, '_pw_runner', None):
            return {
                'dom_available': False,
                'has_page': False,
                'current_url': None
            }
        try:
            s = self._pw_runner.status() if getattr(self, '_pw_runner', None) else {}
            cur = s.get('current_url')
            # 规范化显示：若为搜索页面，统一为百度搜索 URL（https://www.baidu.com/s?wd=...）
            norm = self._canonical_search_url(cur) if cur else None
            return {
                'dom_available': getattr(self, 'dom_available', False),
                'has_page': s.get('has_page', False),
                'current_url': norm
            }
        except Exception:
            return {
                'dom_available': getattr(self, 'dom_available', False),
                'has_page': False,
                'current_url': None
            }

    # ================= [新增] 语义交互接口 =================

    def dom_scan(self) -> str:
        """扫描当前页面，返回带 ID 的元素地图"""
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_scan"
        if not self._ensure_playwright(): return "❌ 浏览器未启动"
        res = self._pw_runner.scan_page()
        if not res: return "⚠️ 页面为空或未检测到可交互元素"
        # 截取前 80 个元素防止 Token 爆炸，通常头部和内容区在前 80 个里
        return f"【页面元素地图】\n{res}" 

    def dom_click_id(self, id: int) -> str:
        """点击指定 ID 的元素"""
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_click_id"
        if not self._ensure_playwright(): return "❌ 浏览器未启动"
        res = self._pw_runner.interact_id('click', id)
        if res.get('ok'):
            return f"✅ 已点击 ID [{id}]"
        return f"❌ 点击失败: {res.get('error')}"

    def dom_fill_id(self, id: int, value: str) -> str:
        """在指定 ID 的元素输入文字"""
        # DEPRECATED: DOM operations disabled
        return "❌ DOM 操作已弃用: dom_fill_id"
        if not self._ensure_playwright(): return "❌ 浏览器未启动"
        res = self._pw_runner.interact_id('fill', id, value)
        if res.get('ok'):
            return f"✅ 已在 ID [{id}] 输入: {value}"
        return f"❌ 输入失败: {res.get('error')}"

    def click_text(self, text: str, clicks: int = 1, interval: float = 0.0, button: str = 'left') -> str:
        """
        OCR 已弃用的占位方法 — 请使用 DOM 接口（dom_query / dom_click / dom_open）来完成网页元素定位与点击。
        """
        # 项目已全面停用基于图像的屏幕识别；保留该 API 以兼容但始终返回弃用提示
        return "❌ 已弃用：请使用 DOM 工具（例如 dom_query / dom_click / dom_open）。"
