from modules.agent.executor import ActionExecutor
import time, json

print('=== search_manus_and_open ===')
ae = ActionExecutor()
# 使用百度搜索作为默认引擎
search_url = 'https://www.baidu.com/s?wd=manus'
print('dom_open ->', ae.dom_open(search_url, headless=False))
# 等待页面加载
time.sleep(3)
# 先预览常见的搜索结果链接（百度）
preview = ae.dom_preview('div.result h3 a', max_results=8)
print('preview ->', preview)
if not preview:
    preview = ae.dom_preview('div.result a', max_results=8)
    print('fallback preview ->', preview)

if preview:
    print('clicking first preview (index=0) ->', ae.dom_click('div.result h3 a', index=0, timeout=15000))
    time.sleep(2)
    print('current_url ->', ae.dom_eval('location.href'))
else:
    print('❌ 未找到搜索结果的候选元素，尝试点击第一个外部链接选择器')
    res = ae.dom_query('a[href^="http"]', multiple=True)
    print('a[href^="http"] count ->', len(res))
    if res:
        print('clicking first http link ->', ae.dom_click('a[href^="http"]', index=0, timeout=15000))
        time.sleep(2)
        print('current_url ->', ae.dom_eval('location.href'))
    else:
        print('❌ 无可点击链接')

print('dom_status ->', ae.dom_status())
print('=== done ===')
