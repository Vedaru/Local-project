from modules.agent.core import ManusAgent

# dummy llm/tools for testing
agent = ManusAgent(lambda *a, **k: '', None, model_name='test', system_prompt='')

cases = [
    # clean JSON
    '{"thought":"x","tool":"final_answer","args":{"summary":"1. a\\n2. b"}}',
    # JSON inside code fence
    '```json\n{"thought":"x","tool":"final_answer","args":{"summary":"ok"}}\n```',
    # single quotes + Python True
    "{'thought':'x','tool':'final_answer','args':{'summary':'ok','flag':True}}",
    # trailing comma
    '{"thought":"x","tool":"final_answer","args":{"a":1,}, "extra": 1}',
    # smart quotes and zero-width chars
    '\u200b“{"thought":"x","tool":"final_answer","args":{"summary":"ok"}}”',
    # user's real-world example (contains apostrophe inside the summary)
    '{"thought":"根据搜索结果整理DeepSeek最新动态","tool":"final_answer","args":{"summary":"1. DeepSeek V4预计将在2026年2月中旬(春节期间)发布\\n2. V4版本将支持100万token上下文长度\\n3. DeepSeek近期更新引发热议,有用户反馈模型 风格变得更\'冷漠\'\\n4. DeepSeek正在完善开源生态,开发者数量快速增长\\n5. DeepSeek成立于2023年,专注于通用人工智能底层模型研究"}}',
]

for i, c in enumerate(cases, 1):
    parsed = agent._extract_json(c)
    print(i, '=>', parsed)
