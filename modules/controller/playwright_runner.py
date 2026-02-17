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

    # --- 新增：全页语义扫描（semantic DOM map） ---
    async def _get_semantic_dom(self):
        """在页面上执行 JS，提取所有可交互且可见的重要元素并在 DOM 上打上 data-seeka-id（从 0 开始）。

        返回：{ok: True, items: [...], text: "[0] <link> \"...\"\n..."}
        每个 item 包含 {id, tag, text, summary, box}
        """
        if not self._page:
            return {'ok': False, 'error': 'no_page'}

        js = r'''
(function(){
  const selectors = ['a','button','input','textarea','select','h1','h2','h3','h4','h5','h6','span','p','div'];
  const nodeList = Array.from(document.querySelectorAll(selectors.join(',')));
  const out = [];
  function isVisible(el){
    if(!el) return false;
    if(el.tagName === 'INPUT' && (el.type||'').toLowerCase() === 'hidden') return false;
    const style = window.getComputedStyle(el);
    if(!style || style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity||1) === 0) return false;
    if(el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true') return false;
    const rect = el.getBoundingClientRect();
    if(!rect || rect.width <= 0 || rect.height <= 0) return false;
    if(rect.width * rect.height <= 0) return false;
    if(!document.body.contains(el)) return false;
    return true;
  }

  let idx = 0;
  for(const el of nodeList){
    try{
      if(!isVisible(el)) continue;
      const tag = (el.tagName||'').toLowerCase();
      let text = '';
      if(['a','button','h1','h2','h3','h4','h5','h6','span','p','div'].includes(tag)){
        text = (el.innerText || '').trim();
      } else if(tag === 'input' || tag === 'textarea'){
        text = (el.getAttribute('placeholder') || el.getAttribute('aria-label') || (el.value||'')) + '';
      } else if(tag === 'select'){
        const opt = el.options && el.selectedIndex >= 0 ? (el.options[el.selectedIndex] && el.options[el.selectedIndex].text) : '';
        text = (el.getAttribute('aria-label') || el.name || opt || '') + '';
      }

      if(!text && ['div','span','p'].includes(tag)){
        continue;
      }

      const rect = el.getBoundingClientRect();
      const summary = (text || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('placeholder') || (el.href||'') || el.className || '').toString().trim().slice(0,240);
      el.setAttribute('data-seeka-id', String(idx));
      out.push({id: idx, tag: tag, text: (text||'').toString().trim().slice(0,240), summary: summary, box: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)}});
      idx += 1;
    }catch(e){ }
  }
  return out;
})()
'''
        try:
            items = await self._page.evaluate(js)
        except Exception as e:
            return {'ok': False, 'error': 'evaluate_failed', 'detail': str(e)}

        try:
            self._last_semantic_map = items or []
        except Exception:
            self._last_semantic_map = items or []

        lines = []
        for it in (items or []):
            idx = it.get('id')
            tag = it.get('tag') or ''
            text = (it.get('text') or it.get('summary') or '').replace('\n', ' ').strip()
            text = text[:240]
            lines.append(f"[{idx}] <{tag}> \"{text}\"")

        return {'ok': True, 'items': items or [], 'text': '\n'.join(lines)}

    async def _click_by_semantic_id(self, sid):
        """通过 data-seeka-id 属性查找元素并点击。sid 支持数字或字符串。"""
        if not self._page:
            return {'ok': False, 'error': 'no_page'}
        if sid is None:
            return {'ok': False, 'error': 'no_id'}
        sid_str = str(sid)
        try:
            handle = await self._page.query_selector(f'[data-seeka-id="{sid_str}"]')
        except Exception as e:
            return {'ok': False, 'error': 'query_failed', 'detail': str(e)}
        if not handle:
            return {'ok': False, 'error': 'no_match'}

        try:
            try:
                await handle.scroll_into_view_if_needed()
            except Exception:
                try:
                    await handle.evaluate('el => el.scrollIntoView({block: "center", inline: "nearest"})')
                except Exception:
                    pass
            await handle.click()
            return {'ok': True}
        except Exception as e_click:
            try:
                js = f"(function(){{ const el = document.querySelector('[data-seeka-id=\"{sid_str}\"]'); if(!el) return false; el.click(); return true; }})()"
                res = await self._page.evaluate(js)
                if res:
                    return {'ok': True, 'fallback': 'js'}
            except Exception:
                pass
            return {'ok': False, 'error': 'click_error', 'detail': str(e_click)}

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

    # --- 同步包装器 for semantic methods ---
    def get_semantic_dom(self):
        return self._run(self._get_semantic_dom())

    def click_by_semantic_id(self, sid):
        return self._run(self._click_by_semantic_id(sid))
