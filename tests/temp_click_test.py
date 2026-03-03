import sys

sys.path.append(r"d:\Personal_Files\Projects\Github\Local-project")
import json

from modules.agent import agent_tools, core


def fake_llm(sp, mn, prompt, mc=""):
    # always instruct browsing to bilibili
    return json.dumps({"thought": "", "tool": "browse", "args": "https://www.bilibili.com"})


tools = agent_tools.AgentTools()
agent = core.ManusAgent(fake_llm, tools, model_name="test", system_prompt="")
print("running task...")
res = agent.run_task("打开b站并点击第一个视频")
print("result", res)
