from modules.agent.browser import BrowserAgent
import json

if __name__ == '__main__':
    agent = BrowserAgent()
    goal = "打开哔哩哔哩首页并搜索“人工智能”相关视频，点击第一个时长超过10分钟的视频链接。"    
    # simplified autonomous loop - agent plans using DOM information
    last_action = None
    repeat_count = 0
    empty_scan_count = 0
    sent_goal = False
    success = False

    for i in range(20):
        dom = agent.observe()
        print("DOM 元素数：", len(dom))
        # only provide goal on first call
        prompt_goal = goal if not sent_goal else ""
        action = agent.think(prompt_goal, dom)
        sent_goal = True
        print("模型返回：", action)

        res = agent.act(action)
        print("执行：", res)

        # detect repeated actions (excluding redundant search-button clicks)
        if action == last_action and '"click", "id": 11' not in action:
            repeat_count += 1
        else:
            repeat_count = 0
        # if the same type action (typing) repeats, assume input step done
        if repeat_count >= 1 and '"action": "type"' in action:
            print("连续重复输入同一元素，认为输入完成，退出循环")
            break
        last_action = action

        # detect empty scans
        if action.strip().startswith('{') and 'scan' in action and len(dom) == 0:
            empty_scan_count += 1
        else:
            empty_scan_count = 0

        # stop when agent says finished
        try:
            act_obj = json.loads(action)
            if act_obj.get('action') == 'finish':
                print("任务完成，退出循环")
                break
        except Exception:
            pass

        # break if stuck scanning empty page or repeating same action too often
        if empty_scan_count >= 3 or repeat_count >= 5:
            print("代理似乎陷入循环，退出")
            break

    if not success:
        print("未在限定步骤内找到符合条件的视频链接。")
    agent.close()
