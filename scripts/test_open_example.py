from modules.controller.executor import ActionExecutor
import time

print('=== test_open_example ===')
ae = ActionExecutor()
print('dom_open ->', ae.dom_open('https://example.com', headless=False))
# 等待
time.sleep(2)
print('dom_status ->', ae.dom_status())
print('=== done ===')
