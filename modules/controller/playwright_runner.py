"""
playwright_runner.py

将 Playwright 后台 runner 与线程/asyncio 管理独立成模块，供
`ActionExecutor`（或其它调用方）按需导入并使用。

对外暴露的实例方法与原嵌套类保持兼容：
- open / navigate / query / click / click_index / fill / evaluate / status

该类在内部维护一个独立的 asyncio loop 并在后台线程中运行 Playwright。
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

    # --- async operations (copied behavior from original implementation) ---
    async def _open(self, bt: str, url: str | None, headless: bool, executable_path: str | None):
        # normalize search / google -> baidu logic preserved by caller if needed
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
        await self._page.fill(sel, value)
        return {'ok': True}

    async def _eval(self, expression: str):
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        res = await self._page.evaluate(expression)
        return {'ok': True, 'result': res}

    async def _status(self):
        return {
            'has_page': bool(self._page),
            'current_url': getattr(self._page, 'url', None) if self._page else None
        }

    # --- sync wrappers exposed to caller thread ---
    def open(self, bt: str, url: str | None, headless: bool, executable_path: str | None):
        return self._run(self._open(bt, url, headless, executable_path))

    def navigate(self, url: str, timeout: int = 15000):
        return self._run(self._navigate(url, timeout))

    def query(self, selector: str, by: str = 'css', multiple: bool = False):
        return self._run(self._query(selector, by, multiple))

    def click(self, selector: str, by: str = 'css', timeout: int = 5000):
        return self._run(self._click(selector, by, timeout))

    def click_index(self, selector: str, by: str = 'css', index: int = 0, timeout: int = 5000):
        return self._run(self._click_by_index(selector, by, index, timeout))

    def fill(self, selector: str, value: str, by: str = 'css'):
        return self._run(self._fill(selector, value, by))

    def evaluate(self, expression: str):
        return self._run(self._eval(expression))

    def status(self):
        return self._run(self._status())
