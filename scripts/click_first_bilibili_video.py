from modules.controller.executor import ActionExecutor
import time

def click_first_video(timeout=15):
    ae = ActionExecutor()
    print('open blank ->', ae.dom_open(None, headless=False))
    print('navigate ->', ae.dom_navigate('https://www.bilibili.com'))

    sel = 'a[href^="https://www.bilibili.com/video/"]'
    deadline = time.time() + timeout
    found = []
    while time.time() < deadline:
        found = ae.dom_query(sel, multiple=True)
        if found:
            break
        time.sleep(0.5)

    print('found count:', len(found))
    if not found:
        return '❌ 未能在页面上找到视频链接（超时）'

    print('clicking selector ->', sel)
    res = ae.dom_click(sel)
    # 等待导航
    time.sleep(2)
    status = ae.dom_status()
    return {'click_result': res, 'status': status, 'first_video': found[0]}

if __name__ == '__main__':
    print('=== click_first_bilibili_video ===')
    out = click_first_video()
    print('result ->', out)
    print('=== done ===')
