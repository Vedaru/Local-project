"""
执行模块 - PyAutoGUI 封装
负责实际执行电脑控制操作
"""

import subprocess
import os
import pyautogui
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


    # ----------------- 窗口管理工具 -----------------
    def _capture_window_titles(self):
        """返回当前可见窗口标题集合（用于比较新打开的窗口）"""
        try:
            import pygetwindow as gw
            return set([w.title for w in gw.getAllWindows() if w.title and w.title.strip()])
        except Exception:
            # 回退为空集合，比较时将无法识别新增窗口
            return set()

    def _maximize_new_windows(self, before_titles: set, title_hint: str = None, timeout: float = 3.0) -> int:
        """查找在 before_titles 之后新出现的窗口并尝试最大化。返回最大化窗口数量。"""
        try:
            import time
            import pygetwindow as gw
            end = time.time() + timeout
            maximized = 0
            while time.time() < end:
                all_windows = [w for w in gw.getAllWindows() if w.title and w.title.strip()]
                new_windows = [w for w in all_windows if w.title not in before_titles]
                if title_hint:
                    new_windows = [w for w in new_windows if title_hint.lower() in w.title.lower()]
                if new_windows:
                    for w in new_windows:
                        try:
                            w.maximize()
                            maximized += 1
                            logger.info(f"已最大化窗口: {w.title}")
                        except Exception as e:
                            logger.debug(f"最大化窗口失败: {w.title} -> {e}")
                    break
                time.sleep(0.2)
            return maximized
        except Exception as e:
            logger.debug(f"_maximize_new_windows 失败: {e}")
            # 退回到发送快捷键（尝试最大化当前活动窗口）
            try:
                import pyautogui
                pyautogui.hotkey('win', 'up')
                return 1
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
    from .playwright_runner import PlaywrightRunner as _PlaywrightRunner

    # (Playwright runner implementation moved to modules.controller.playwright_runner for modularity)

    def _ensure_playwright(self) -> bool:
        """确保 Playwright 后台 runner 已启动并可用（线程安全）。"""
        if getattr(self, 'dom_available', False) and getattr(self, '_pw_runner', None):
            return True
        try:
            # 先检测包是否存在
            try:
                from playwright.async_api import async_playwright  # noqa: F401
            except Exception as ie:
                logger.warning(f'Playwright 包不可用: {ie}')
                self.dom_available = False
                return False

            # 启动后台 runner（若尚未启动）
            if not getattr(self, '_pw_runner', None):
                runner_cls = getattr(self, '_PlaywrightRunner', None) or type(self)._PlaywrightRunner
                self._pw_runner = runner_cls()

            # 简单检查是否已启动
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

    def dom_open(self, url: str = None, browser_type: str = None, headless: bool = False, browser_path: str = None) -> str:
        """使用 Playwright 打开浏览器并导航（线程安全）。"""
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
                            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
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

            # 规范化传入的 URL：裸词/查询 -> 转为百度搜索 URL
            from .dom_utils import canonical_search_url
            norm_input = canonical_search_url(url) if url else url

            res = self._pw_runner.open(bt, norm_input, headless, exec_path)
            if res.get('ok'):
                final_url = res.get('url') or norm_input or url
                # 规范化用于显示（例如把 google 搜索重写为 baidu）
                norm = canonical_search_url(final_url) if final_url else final_url
                logger.info(f"dom_open: 打开 {bt} 成功, url={final_url}")
                used = f" ({'Edge' if exec_path and 'msedge' in (exec_path or '').lower() else bt})"
                return f"✅ DOM 浏览器已启动{used} 并导航到: {norm or (final_url or 'about:blank')}"
            else:
                return f"❌ dom_open 失败: {res.get('error', 'unknown')}"
        except Exception as e:
            logger.error(f"dom_open 失败: {e}", exc_info=True)
            return f"❌ dom_open 失败: {e}"

    def dom_navigate(self, url: str, timeout: int = 15000) -> str:
        try:
            res = self._pw_runner.navigate(url, timeout)
            if res.get('ok'):
                return f"✅ 已导航到: {url}"
            return f"❌ 导航失败: {res.get('error')}"
        except Exception as e:
            return f"❌ 导航失败: {e}"

    def dom_query(self, selector: str, by: str = 'css', multiple: bool = False, timeout: int = 5000):
        try:
            return self._pw_runner.query(selector, by=by, multiple=multiple)
        except Exception as e:
            logger.error(f"dom_query 失败: {e}", exc_info=True)
            return []

    def dom_preview(self, selector: str, by: str = 'css', max_results: int = 6, timeout: int = 5000):
        """列出匹配 selector 的候选元素（用于让用户/Agent 先确认再点击）。

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
                preview.append({
                    'index': i,
                    'text': text,
                    'href': href,
                    'attributes': it.get('attributes', {}),
                    'box': it.get('box', {}),
                    'summary': summary[:240]
                })
            return preview
        except Exception as e:
            logger.error(f"dom_preview 失败: {e}", exc_info=True)
            return []

    def dom_click(self, selector: str, by: str = 'css', timeout: int = 5000, index: Optional[int] = None) -> str:
        """在 DOM 页面上点击元素 — **仅使用回退策略**（query -> click_index / 候选 selector）。

        说明：根据你的要求，删除了对 locator.click 的直接尝试，始终通过查询匹配集合并按索引点击（更稳定、可控）。
        """
        if not getattr(self, '_pw_runner', None):
            return "❌ DOM runner 未初始化。"

        try:
            # 只使用回退策略：构建候选 selector 列表并按顺序尝试
            from .dom_utils import generate_click_candidates
            candidates = generate_click_candidates(selector)

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
        try:
            res = self._pw_runner.fill(selector, value, by=by)
            if res.get('ok'):
                return f"✅ 已填入文本到 {selector}"
            return f"❌ dom_fill 失败: {res.get('error')}"
        except Exception as e:
            logger.error(f"dom_fill 失败: {e}", exc_info=True)
            return f"❌ dom_fill 失败: {e}"

    def dom_eval(self, expression: str):
        try:
            res = self._pw_runner.evaluate(expression)
            if isinstance(res, dict) and not res.get('ok', True):
                return f"❌ dom_eval 失败: {res.get('error')}"
            return res.get('result') if isinstance(res, dict) and 'result' in res else res
        except Exception as e:
            logger.error(f"dom_eval 失败: {e}", exc_info=True)
            return f"❌ dom_eval 失败: {e}"

    def _canonical_search_url(self, url: str | None) -> str | None:
        """若 URL 为搜索页面或裸词，返回规范化的百度搜索 URL（https://www.baidu.com/s?wd=...），否则返回原 URL。"""
        try:
            if not url:
                return None
            from urllib.parse import urlparse, parse_qs, urlencode
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

    def click_text(self, text: str, clicks: int = 1, interval: float = 0.0, button: str = 'left') -> str:
        """
        OCR 已弃用的占位方法 — 请使用 DOM 接口（dom_query / dom_click / dom_open）来完成网页元素定位与点击。
        """
        # 保留参数以兼容旧调用；显式引用以避免静态分析误报
        _ = (clicks, interval, button)
        # 项目已全面停用基于图像的屏幕识别；保留该 API 以兼容但始终返回弃用提示
        return "❌ 已弃用：请使用 DOM 工具（例如 dom_query / dom_click / dom_open）。"
