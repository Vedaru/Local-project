from modules.agent.executor import ActionExecutor
from modules.agent.controller import ComputerController
from modules.agent.safety import SafetyGuard

ae = ActionExecutor(failsafe=False)
cc = ComputerController(SafetyGuard({}), ae)
print('dom_available =', getattr(ae,'dom_available',None))
print('action_executor.dom_open signature default (will try Edge if available)')
# `open_browser` 已移除 - Agent/LLM 不应再生成该指令；请使用 dom_open
print('call dom_open ->', cc._execute_action({'action':'dom_open','url':'https://example.com'}))
