"""
PlaywrightRunner — 在后台线程中运行 Playwright 的独立实现（从 controller.playwright_runner 迁移）

提供与原有嵌套实现兼容的同步包装方法：open / navigate / query / click / click_index / fill / evaluate / status
"""
from __future__ import annotations
import threading
import asyncio
import json
from typing import Optional


class PlaywrightRunner:
    """在后台线程里运行 Playwright asyncio loop 的独立实现。

    API 与原 `ActionExecutor._PlaywrightRunner` 行为兼容（同步包装异步协程）。
    """
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._apw = None
        self._browser = None
        self._context = None
        self._page = None
        self.started = threading.Event()
        self._start_thread()

    def _start_thread(self):
        def _main():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._init_playwright())
            except Exception:
                pass
            self.started.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    self._loop.run_until_complete(self._shutdown())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_main, daemon=True)
        self._thread.start()
        self.started.wait(timeout=6)

    async def _init_playwright(self):
        from playwright.async_api import async_playwright
        self._apw = await async_playwright().start()

    async def _shutdown(self):
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._apw:
                await self._apw.stop()
        except Exception:
            pass

    def _run(self, coro):
        if not self._loop or self._loop.is_closed():
            raise RuntimeError('Playwright runner 未启动')
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    # --- async operations (保持与原实现一致) ---
    async def _open(self, bt: str, url: str | None, headless: bool, executable_path: str | None):
        bt_attr = getattr(self._apw, bt)
        launch_kwargs = {'headless': headless}
        if executable_path:
            launch_kwargs['executable_path'] = executable_path
        browser = await bt_attr.launch(**launch_kwargs)
        context = await browser.new_context()
        page = await context.new_page()
        if url:
            await page.goto(url, timeout=15000)
        self._browser = browser
        self._context = context
        self._page = page
        return {'ok': True, 'url': url}

    async def _navigate(self, url: str, timeout: int = 15000):
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        await self._page.goto(url, timeout=timeout)
        return {'ok': True, 'url': url}

    async def _query(self, selector: str, by: str, multiple: bool):
        if not self._page:
            return []
        sel = f'xpath={selector}' if by == 'xpath' else selector
        if multiple:
            handles = await self._page.query_selector_all(sel)
        else:
            h = await self._page.query_selector(sel)
            handles = [h] if h else []
        results = []
        for el in handles:
            try:
                text = await el.inner_text()
            except Exception:
                text = ''
            try:
                inner = await el.inner_html()
            except Exception:
                inner = ''
            try:
                attrs = await el.evaluate("e => { const a={}; for(const at of e.attributes) a[at.name]=at.value; return a }")
            except Exception:
                attrs = {}
            try:
                bbox = await el.bounding_box() or {}
                bbox = {k: int(v) for k, v in bbox.items()} if bbox else {}
            except Exception:
                bbox = {}
            results.append({'text': text, 'innerHTML': inner, 'attributes': attrs, 'box': bbox})
        return results

    async def _click(self, selector: str, by: str, timeout: int = 5000):
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        sel = selector if by == 'css' else f'xpath={selector}'
        try:
            await self._page.locator(sel).first.click(timeout=timeout)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': 'click_error', 'detail': str(e)}

    async def _click_by_index(self, selector: str, by: str, index: int = 0, timeout: int = 5000):
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        sel = selector if by == 'css' else f'xpath={selector}'
        try:
            handles = await self._page.query_selector_all(sel)
        except Exception as e:
            return {'ok': False, 'error': 'query_failed', 'detail': str(e)}
        if not handles:
            return {'ok': False, 'error': 'no_match'}
        if index < 0 or index >= len(handles):
            return {'ok': False, 'error': 'index_out_of_range'}
        try:
            try:
                await handles[index].scroll_into_view_if_needed()
            except Exception:
                try:
                    await handles[index].evaluate("el => el.scrollIntoView({block:'center', inline:'nearest'})")
                except Exception:
                    pass
            await handles[index].click(timeout=timeout)
            return {'ok': True}
        except Exception as e_click:
            try:
                await self._page.locator(sel).nth(index).click(timeout=timeout, force=True)
                return {'ok': True}
            except Exception as e_force:
                try:
                    js_sel = json.dumps(sel)
                    js = (
                        f"(function(){{ const els = document.querySelectorAll({js_sel}); if(!els||!els[{index}]) return false; els[{index}].click(); return true; }})()"
                    )
                    await self._page.evaluate(js)
                    return {'ok': True}
                except Exception as e_js:
                    detail = f"handles_click_error: {e_click}; locator_force_error: {e_force}; js_error: {e_js}"
                    return {'ok': False, 'error': 'click_error', 'detail': detail}

    async def _fill(self, selector: str, value: str, by: str = 'css'):
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        sel = selector if by == 'css' else f'xpath={selector}'
        
        try:
            # 1. 聚焦元素 (B站的关键：必须先点一下，激活输入框)
            await self._page.focus(sel)
            
            # 2. 模拟真实打字 (type 比 fill 更能触发网页逻辑)
            # 这里的 delay 模拟人类打字速度，防止被网页判定为脚本瞬间注入而被清空
            await self._page.fill(sel, "") # 先清空
            await self._page.type(sel, value, delay=50) 
            
            # 3. 【核心步骤】校验填入是否成功
            current_val = await self._page.input_value(sel)
            
            # 如果填入失败（比如变成了推荐词），使用 JS 暴力覆盖
            if current_val != value:
                print(f"⚠️ [DOM] 标准输入失效 (当前值: {current_val})，尝试 JS 强制注入...")
                js_code = f"""
                    const el = document.querySelector('{sel}');
                    if(el) {{
                        el.value = '{value}';
                        // 必须触发以下事件，B站才会承认这个值
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('blur', {{ bubbles: true }})); // 失去焦点锁定值
                    }}
                """
                await self._page.evaluate(js_code)
            
            return {'ok': True}
            
        except Exception as e:
            return {'ok': False, 'error': f"fill_failed: {str(e)}"}
    async def _eval(self, expression: str):
        """Evaluate a JS expression in page context and return standardized result dict."""
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        try:
            # Playwright accepts raw JS expressions / function bodies — delegate directly.
            res = await self._page.evaluate(expression)
            return {'ok': True, 'result': res}
        except Exception as e:
            return {'ok': False, 'error': 'evaluate_error', 'detail': str(e)}

    async def _status(self):
        """Return simple runner/page status used by `dom_status()`."""
        return {
            'has_page': bool(self._page),
            'current_url': (self._page.url if self._page else None)
        }

    # --- sync wrappers exposed to caller thread ---
    def open(self, bt: str, url: str | None, headless: bool, executable_path: str | None):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._open(bt, url, headless, executable_path))

    def navigate(self, url: str, timeout: int = 15000):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._navigate(url, timeout))

    def query(self, selector: str, by: str = 'css', multiple: bool = False):
        # DEPRECATED: DOM operations disabled
        return []
        # return self._run(self._query(selector, by, multiple))

    def click(self, selector: str, by: str = 'css', timeout: int = 5000):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._click(selector, by, timeout))

    def click_index(self, selector: str, by: str = 'css', index: int = 0, timeout: int = 5000):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._click_by_index(selector, by, index, timeout))

    def fill(self, selector: str, value: str, by: str = 'css'):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._fill(selector, value, by))

    def evaluate(self, expression: str):
        # DEPRECATED: DOM operations disabled
        return {'ok': False, 'error': 'dom_disabled'}
        # return self._run(self._eval(expression))

    def status(self):
        # DEPRECATED: DOM operations disabled
        return {'has_page': False, 'current_url': None}
        # return self._run(self._status())

    # ================= [新增] 全页扫描核心逻辑 =================

    async def _scan_page(self):
        """注入 JS，给所有交互元素打标，并返回列表"""
        if not self._page: return []
        
        # 这一大段 JS 是核心：清洗旧ID -> 寻找可见元素 -> 打新ID -> 提取文本
        js_script = """
        () => {
            // 1. 清理旧标签
            document.querySelectorAll('[data-seeka-id]').forEach(el => el.removeAttribute('data-seeka-id'));
            
            let items = [];
            let id_counter = 0;
            
            // 2. 定义什么是"可交互元素"
            const selectors = 'a, button, input, textarea, select, [role="button"], [onclick]';
            
            document.querySelectorAll(selectors).forEach(el => {
                // 3. 过滤不可见元素 (面积为0，或样式隐藏)
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || rect.width === 0 || rect.height === 0) return;
                
                // 4. 提取关键信息
                let tag = el.tagName.toLowerCase();
                let text = (el.innerText || el.placeholder || el.value || el.getAttribute('aria-label') || "").replace(/\s+/g, ' ').trim();
                
                // 5. 只有有意义的元素才打标 (有文字，或者是输入框)
                if (text.length > 0 || tag === 'input' || tag === 'textarea') {
                    el.setAttribute('data-seeka-id', id_counter);
                    
                    // 格式化输出: [ID] <标签> "内容"
                    items.push(`[${id_counter}] <${tag}> "${text.substring(0, 50)}"`);
                    id_counter++;
                }
            });
            return items.join('\n');
        }
        """
        
        try:
            result = await self._page.evaluate(js_script)
            return result
        except Exception as e:
            return f"扫描脚本执行失败: {e}"

    async def _interact_by_id(self, action_type, id, value=None):
        """根据 data-seeka-id 定位并操作"""
        if not self._page: return {'ok': False, 'error': 'no_page'}
        
        selector = f'[data-seeka-id="{id}"]'
        try:
            # 滚动到可见区域
            locator = self._page.locator(selector).first
            if await locator.count() == 0:
                return {'ok': False, 'error': f'ID {id} not found (可能页面已刷新)'}
                
            await locator.scroll_into_view_if_needed()
            
            if action_type == 'click':
                # 强制点击，无视遮挡
                await locator.click(force=True)
            elif action_type == 'fill':
                await locator.fill(str(value))
                
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # --- 同步包装器 (供 Executor 调用) ---
    def scan_page(self):
        return self._run(self._scan_page())
        
    def interact_id(self, action_type, id, value=None):
        return self._run(self._interact_by_id(action_type, id, value))
