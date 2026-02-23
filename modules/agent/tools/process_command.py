from typing import Tuple
import re
import json


def process_command(agent_tools, response_text: str) -> Tuple[str, str]:
    """处理 AI 响应文本，提取并执行控制指令。

    返回 (execution_log, clean_text)。
    """
    action_pattern = r'\[ACTION\](.*?)\[/ACTION\]'
    matches = re.findall(action_pattern, response_text, re.DOTALL)
    if not matches:
        return "", response_text
    execution_logs = []
    for action_json in matches:
        try:
            action_data = json.loads(action_json.strip())
            if not isinstance(action_data, dict) or 'action' not in action_data:
                execution_logs.append("❌ 指令解析失败: 缺少 'action' 字段")
                continue
            log = agent_tools._execute_action(action_data)
            execution_logs.append(log)
        except json.JSONDecodeError as e:
            execution_logs.append(f"❌ 指令解析失败: 无效的 JSON 格式 - {str(e)}")
        except Exception as e:
            execution_logs.append(f"❌ 执行失败: {str(e)}")
    execution_log = " | ".join(execution_logs) if execution_logs else ""
    clean_text = re.sub(action_pattern, '', response_text, flags=re.DOTALL).strip()
    return execution_log, clean_text
