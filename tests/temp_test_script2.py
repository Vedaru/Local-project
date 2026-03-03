import os
import sys

sys.path.append(r"d:\Personal_Files\Projects\Github\Local-project")
from modules.agent import agent_tools

tools = agent_tools.AgentTools()
print(tools.open_local_app("notepad"))
import time

# wait a bit for notepad
time.sleep(1)
print("typing result:", tools.type_text("我的名字是洛可！"))
