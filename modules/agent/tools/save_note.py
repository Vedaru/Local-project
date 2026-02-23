import os
from datetime import datetime
import logging

logger = logging.getLogger('AgentTools.save_note')

def save_note_to_desktop(content: str, filename: str | None = None) -> str:
    """将内容保存到用户桌面，返回结果消息。"""
    try:
        desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'note_{timestamp}.txt'
        if not filename.endswith('.txt'):
            filename += '.txt'
        file_path = os.path.join(desktop_path, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"✅ 成功保存笔记到桌面: {filename}"
    except Exception as e:
        logger.error(f"save_note_to_desktop failed: {e}", exc_info=True)
        return f"❌ 保存笔记失败, 错误: {e}"
