"""file_tools — 文件相关小工具（从 ActionExecutor.save_note 拆分）

导出：save_note_to_desktop(content, filename=None)
"""
import os
from datetime import datetime


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
        return f"❌ 保存笔记失败, 错误: {e}"