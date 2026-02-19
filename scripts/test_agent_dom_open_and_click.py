from modules.agent.safety import SafetyGuard
from modules.agent.executor import ActionExecutor
from modules.agent.controller import ComputerController
from modules.agent.tools import AgentTools
import time

print('=== test_agent_dom_open_and_click ===')
# 构造最小依赖的环境（用于 demo / 测试）
sg = SafetyGuard({})
ae = ActionExecutor()
cc = ComputerController(sg, ae)
tools = AgentTools(controller=cc)

args = {
    'url': 'https://www.bilibili.com',
    'selector': 'a[href^="https://www.bilibili.com/video/"]',
    'timeout': 15
}
print('calling AgentTools.execute("dom_open_and_click", args)')
res = tools.execute('dom_open_and_click', args)
print('result ->', res)
# 查询状态
print('dom_status ->', cc.action_executor.dom_status())
print('=== done ===')
