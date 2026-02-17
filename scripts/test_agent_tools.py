from modules.agent.tools import AgentTools

def expect_equal(a, b):
    print('OK' if a == b else f'FAIL -> got: {a!r} expected: {b!r}')

at = AgentTools()

print('--- AgentTools smoke tests (controller=None) ---')
expect_equal(at.execute('scan_page_elements', None), '❌ 未提供 ComputerController，无法执行 scan_page_elements')
expect_equal(at.execute('scanPageElements', None), '❌ 未提供 ComputerController，无法执行 scan_page_elements')
expect_equal(at.execute('click_element_by_id', {'id': 1}), '❌ 未提供 ComputerController，无法执行 click_element_by_id')
expect_equal(at.execute('type_text', {'text': 'x'}), '❌ 未提供 ComputerController，无法执行 type_text')
expect_equal(at.execute('press_key', 'enter'), '❌ 未提供 ComputerController，无法执行 press_key')

print('\nIf all lines show OK, AgentTools maps the names correctly.')
