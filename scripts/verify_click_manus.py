from modules.agent.executor import ActionExecutor

if __name__ == '__main__':
    ae = ActionExecutor()
    print('dom_open ->', ae.dom_open('manus', headless=True))
    preview = ae.dom_preview('li.b_algo h2 a', max_results=6)
    print('dom_preview ->', preview)
    click_res = ae.dom_click('li.b_algo h2 a', index=0)
    print('dom_click ->', click_res)
    print('dom_status ->', ae.dom_status())
