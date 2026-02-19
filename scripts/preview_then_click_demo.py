from modules.agent.safety import SafetyGuard
from modules.agent.executor import ActionExecutor
from modules.agent.controller import ComputerController
from modules.agent.tools import AgentTools
import json, time

print('=== preview_then_click_demo ===')
sg = SafetyGuard({})
ae = ActionExecutor()
cc = ComputerController(sg, ae)
tools = AgentTools(controller=cc)

# 1) 打开页面
print('open ->', tools.execute('dom_open', {'url': 'https://www.bilibili.com'}))
# 等待动态内容
time.sleep(4)

# 2) 预览候选元素
selector = 'a[href^="https://www.bilibili.com/video/"]'
preview_raw = tools.execute('dom_preview', {'selector': selector, 'max_results': 8})
print('preview_raw ->', preview_raw)
try:
    candidates = json.loads(preview_raw)
except Exception:
    candidates = []

# 3) 输出候选摘要供人工/Agent 确认
for c in candidates:
    print(f"index={c['index']} summary={c['summary']!r} href={c.get('href')}")

# 4) 选择索引（示例：点击 index=1）
choice = 1
print(f"点击索引 {choice} ->", tools.execute('dom_click', {'selector': selector, 'index': choice, 'timeout': 10}))
print('dom_status ->', tools.execute('dom_status', {}))
print('=== done ===')
