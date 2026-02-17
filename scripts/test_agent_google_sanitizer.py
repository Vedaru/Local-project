from modules.agent.core import ManusAgent

# fake llm that returns google in first step then a final_answer
def fake_llm(system_prompt, model_name, prompt, memory_context=""):
    if '第一次' in prompt or '任务:' in prompt:
        return '{"thought":"先在 Google 搜索","tool":"dom_open","args":"https://www.google.com/search?q=manus"}'
    return '{"thought":"done","tool":"final_answer","args":"完成"}'

class DummyTools:
    def execute(self, tool, args):
        print(f"DummyTools.execute called -> tool={tool}, args={args}")
        return f"EXECUTED {tool} {args}"

if __name__ == '__main__':
    agent = ManusAgent(llm_fn=fake_llm, tools=DummyTools(), model_name='test-model', system_prompt='test')
    res = agent.run_task('测试 Google rewrite')
    print('Agent run_task result ->', res)
