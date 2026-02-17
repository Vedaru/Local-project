from modules.controller.executor import ActionExecutor
import time

print('=== open_bilibili_and_click ===')
ae = ActionExecutor()
print('open blank ->', ae.dom_open(None, headless=False))
print('navigate ->', ae.dom_navigate('https://www.bilibili.com'))
# 等待页面 JS 加载
print('waiting for content...')
time.sleep(5)
qs = ae.dom_query('a[href^="/video/"]', multiple=True)
print('found video links:', len(qs))
if qs:
    print('first video info:', qs[0])
    res = ae.dom_click('a[href^="/video/"]')
    print('click result ->', res)
else:
    print('no video links found')
print('dom_status ->', ae.dom_status())
print('=== done ===')
