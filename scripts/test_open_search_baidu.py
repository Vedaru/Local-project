from modules.controller.executor import ActionExecutor
import time

print('=== test_open_search_baidu ===')
ae = ActionExecutor()
# 使用非 URL 字符串作为参数，期望在 DOM 中打开百度搜索
print('dom_open(search) ->', ae.dom_open('playwright python examples', headless=False))
# 等待并打印当前 URL
time.sleep(3)
status = ae.dom_status()
current_href = ae.dom_eval('location.href')
print('dom_status ->', status)
print('dom_eval location.href ->', current_href)
# 验证：必须使用百度搜索或页面标题包含中文
url_check = (isinstance(status, dict) and status.get('current_url')) or (current_href or '')
if url_check and ('baidu.com' in url_check or 'www.baidu.com' in url_check):
    print('✅ 已使用百度进行搜索')
else:
    title = ae.dom_eval('document.title')
    print('页面 title=', title)
    if title and any('\u4e00' <= ch <= '\u9fff' for ch in (title or '')):
        print('✅ 页面标题包含中文')
    else:
        print('⚠️ 未检测到百度搜索或中文结果')

print('=== done ===')
