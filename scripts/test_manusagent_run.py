import sys
sys.path.insert(0, r'd:\Personal_Files\Projects\Github\Local-project')
from modules.agent.core import ManusAgent
from modules.agent.tools import AgentTools

def stub_llm(system_prompt, model_name, prompt, memory_context=''):
    # always return a final_answer JSON to stop the agent quickly
    return '{"thought":"done","tool":"final_answer","args":"stub-result"}'

if __name__ == '__main__':
    agent = ManusAgent(stub_llm, AgentTools(None), 'test-model')
    res = agent.run_task('测试日志输出')
    print('Agent returned ->', res)
