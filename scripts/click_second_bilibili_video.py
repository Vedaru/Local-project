from modules.agent.safety import SafetyGuard
from modules.agent.executor import ActionExecutor
from modules.agent.controller import ComputerController
from modules.agent.tools import AgentTools
import time

print('=== click_second_bilibili_video ===')
sg = SafetyGuard({})
ae = ActionExecutor()
cc = ComputerController(sg, ae)
tools = AgentTools(controller=cc)

args = {
    'url': 'https://www.bilibili.com',
    'selector': 'a[href^="https://www.bilibili.com/video/"]',
    'index': 1,
    'timeout': 20
}
print('calling AgentTools.execute("dom_open_and_click", args) for second video')
res = tools.execute('dom_open_and_click', args)
print('result ->', res)
print('dom_status ->', cc.action_executor.dom_status())
print('=== done ===')
