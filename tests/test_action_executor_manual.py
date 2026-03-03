# manual executor demo; not part of automated tests
import os
import sys

# ensure workspace root is on path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# manual demo of the new AgentTools helpers; previously this
# file exercised ActionExecutor directly.
import time

from modules.agent import agent_tools

at = agent_tools.AgentTools()
print("opening notepad via AgentTools.open_local_app")
at.open_local_app("notepad")
print("waiting before typing")
time.sleep(1)
print("typing now via AgentTools.type_text")
print(at.type_text("Hello123"))
print("done")
