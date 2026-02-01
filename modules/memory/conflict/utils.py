"""
冲突检测辅助函数
"""
from .constants import QUESTION_INDICATORS


def extract_user_input(text: str) -> str:
    """从对话文本中提取用户输入部分"""
    if '用户:' in text:
        return text.split('用户:')[1].split('AI:')[0].strip()
    return text


def is_question(text: str) -> bool:
    """检测是否为疑问句"""
    return any(ind in text for ind in QUESTION_INDICATORS)
