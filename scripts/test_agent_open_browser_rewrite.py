from modules.agent.core import ManusAgent

agent = ManusAgent(lambda *a, **k: '', tools=None, model_name='test')

raw = '{"thought":"打开网页","tool":"open_browser","args":"https://example.com"}'
parsed = agent._extract_json(raw)
print('parsed:', parsed)

# emulate ManusAgent run_task rewrite behavior
tool = (parsed.get('tool') or '').strip()
args = parsed.get('args')
if tool == 'open_browser':
    tool = 'dom_open'
    print('rewritten tool ->', tool, ' args ->', args)
else:
    print('no rewrite needed')
