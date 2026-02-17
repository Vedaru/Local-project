from modules.controller.executor import ActionExecutor
import time, json

print('=== start test_playwright_dom ===')
ae = ActionExecutor()
print('dom_open ->', ae.dom_open('https://www.bilibili.com', headless=False))
# 等待页面加载动态内容
time.sleep(4)
qs = ae.dom_query('a[href^="/video/"]', multiple=True)
print('found video links:', len(qs))
print('sample:', qs[0] if qs else 'none')
print('dom_click ->', ae.dom_click('a[href^="/video/"]'))
print('dom_status ->', ae.dom_status())
print('=== end test_playwright_dom ===')
