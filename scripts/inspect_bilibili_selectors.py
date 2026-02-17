from modules.controller.executor import ActionExecutor
import time, json

ae = ActionExecutor()
print('open blank ->', ae.dom_open(None, headless=False))
print('navigate ->', ae.dom_navigate('https://www.bilibili.com'))
# wait longer for dynamic content
time.sleep(6)

selectors = [
    'a[href*="/video/"]',
    'a[href^="https://www.bilibili.com/video/"]',
    'a[class*="title"]',
    'a[class*="card"]',
    'a[title]',
    'a[href*="b23.tv"]',
    'text=BV',
]

for s in selectors:
    try:
        res = ae.dom_query(s, multiple=True)
        print(f'selector: {s} -> count: {len(res)}')
        if res:
            print('sample:', json.dumps(res[0], ensure_ascii=False))
    except Exception as e:
        print('query error for', s, e)

# try evaluating counts
print('all_a_count ->', ae.dom_eval("document.querySelectorAll('a').length"))
print('first_a_href ->', ae.dom_eval("(document.querySelector('a') && document.querySelector('a').href) || null"))
print('document.domain ->', ae.dom_eval('document.domain'))
print('location.href ->', ae.dom_eval('location.href'))
