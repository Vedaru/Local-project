from modules.agent.playwright_runner import PlaywrightRunner
import time
r = PlaywrightRunner()
print('started event', r.started.is_set())
print('apw', r._apw)
print('browser', r._browser)
print('status', r.status())
for i in range(3):
    time.sleep(1)
    print('status', r.status())
