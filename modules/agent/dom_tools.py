"""DOM 工具函数（从 AgentTools 中提取以拆分文件）

这些函数接受一个 `controller`（ComputerController 实例）和 `args`，并返回字符串结果。
目的是将大量的 DOM 处理逻辑从 `tools.py` 中拆分出去，保持单一职责。
"""
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode


def dom_open(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    # 原始实现已被注释
    return "❌ DOM 操作已弃用: dom_open"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_open"
    # if isinstance(args, str):
    #     url = args
    #     browser_type = None
    #     headless = False
    #     browser_path = None
    # else:
    #     url = (args or {}).get('url')
    #     browser_type = (args or {}).get('browser_type')
    #     headless = bool((args or {}).get('headless', False))
    #     browser_path = (args or {}).get('browser_path')
    # # 规范化：若传入显式的 Google 搜索链接，则改写为百度（双层保险）
    # try:
    #     if url:
    #         p = urlparse(url)
    #         hostname = (p.hostname or '').lower()
    #         path = p.path or ''
    #         if not p.scheme or not p.netloc:
    #             url = 'https://www.baidu.com/s?' + urlencode({'wd': url})
    #             p = urlparse(url)
    #             hostname = (p.hostname or '').lower()
    #             path = p.path or ''
    #         if 'google.' in hostname and path.startswith('/search'):
    #             qs = parse_qs(p.query)
    #             qval = qs.get('q', [''])[0]
    #             url = 'https://www.baidu.com/s?' + urlencode({'wd': qval}) if qval else 'https://www.baidu.com'
    # except Exception:
    #     pass
    # payload = {'action': 'dom_open', 'url': url, 'browser_type': browser_type, 'headless': headless, 'browser_path': browser_path}
    # return controller._execute_action(payload)


def dom_navigate(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_navigate"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_navigate"
    # url = args if isinstance(args, str) else (args or {}).get('url')
    # if not url:
    #     return "❌ dom_navigate 需要提供 url 参数"
    # payload = {'action': 'dom_navigate', 'url': url}
    # return controller._execute_action(payload)


def dom_status(controller) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_status"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_status"
    # payload = {'action': 'dom_status'}
    # return controller._execute_action(payload)


def dom_fill(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_fill"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_fill"
    # if isinstance(args, str):
    #     return "❌ dom_fill 需要提供对象格式：{selector, value}"
    # selector = (args or {}).get('selector')
    # value = (args or {}).get('value', '')
    # by = (args or {}).get('by', 'css')
    # if not selector:
    #     return "❌ dom_fill 需要提供 selector 参数"
    # payload = {'action': 'dom_fill', 'selector': selector, 'value': value, 'by': by}
    # return controller._execute_action(payload)


def dom_eval(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_eval"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_eval"
    # expr = args if isinstance(args, str) else (args or {}).get('expression')
    # if not expr:
    #     return "❌ dom_eval 需要提供 expression/字符串参数"
    # payload = {'action': 'dom_eval', 'expression': expr}
    # return controller._execute_action(payload)


def dom_query(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_query"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_query"
    # if isinstance(args, str):
    #     selector = args
    #     by = 'css'
    #     multiple = False
    # else:
    #     selector = (args or {}).get('selector', 'body')
    #     by = (args or {}).get('by', 'css')
    #     multiple = bool((args or {}).get('multiple', False))
    # payload = {'action': 'dom_query', 'selector': selector, 'by': by, 'multiple': multiple}
    # return controller._execute_action(payload)


def dom_preview(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_preview"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_preview"
    # if isinstance(args, str):
    #     selector = args
    #     by = 'css'
    #     max_results = 6
    # else:
    #     selector = (args or {}).get('selector')
    #     by = (args or {}).get('by', 'css')
    #     max_results = int((args or {}).get('max_results', 6))
    # if not selector:
    #     return "❌ dom_preview 需要提供 selector 参数"
    # payload = {'action': 'dom_preview', 'selector': selector, 'by': by, 'max_results': max_results}
    # return controller._execute_action(payload)


def dom_click(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_click"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_click"
    # if isinstance(args, str):
    #     selector = args
    #     by = 'css'
    #     index = None
    #     timeout = 5
    # else:
    #     selector = (args or {}).get('selector')
    #     by = (args or {}).get('by', 'css')
    #     index = (args or {}).get('index', None)
    #     timeout = int((args or {}).get('timeout', 5))
    # if not selector:
    #     return "❌ dom_click 需要提供 selector 参数"
    # payload = {'action': 'dom_click', 'selector': selector, 'by': by, 'timeout': timeout}
    # if index is not None:
    #     payload['index'] = int(index)
    # return controller._execute_action(payload)


def dom_open_and_click(controller, args: Any) -> str:
    # DEPRECATED: DOM operations disabled
    return "❌ DOM 操作已弃用: dom_open_and_click"

    # if not controller:
    #     return "❌ 未提供 ComputerController，无法执行 dom_open_and_click"
    # if isinstance(args, str):
    #     return "❌ dom_open_and_click 需要提供对象格式：{url, selector, timeout?}"
    # selector = (args or {}).get('selector')
    # url = (args or {}).get('url')
    # by = (args or {}).get('by', 'css')
    # timeout = int((args or {}).get('timeout', 15))
    # index = (args or {}).get('index', None)
    # if not selector:
    #     return "❌ dom_open_and_click 需要提供 selector 参数"
    # payload = {'action': 'dom_open_and_click', 'url': url, 'selector': selector, 'by': by, 'timeout': timeout}
    # if index is not None:
    #     payload['index'] = int(index)
    # return controller._execute_action(payload)
