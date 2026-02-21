from modules.agent.executor import ActionExecutor
import logging
logging.basicConfig(level=logging.DEBUG)
a=ActionExecutor()
print('created')
print('dom_available initially', a.dom_available)
res = a._ensure_playwright()
print('ensure returned', res)
print('dom_available after', a.dom_available)
