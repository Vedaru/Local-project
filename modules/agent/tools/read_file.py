import os
import logging

logger = logging.getLogger('AgentTools.read_file')

def read_file(path: str) -> str:
    """读取工作区或绝对路径的文本文件。"""
    logger.debug(f"read_file() path={path}")
    try:
        if not os.path.exists(path):
            logger.warning(f"read_file(): file not found: {path}")
            return f"❌ 文件不存在: {path}"
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()
        logger.debug(f"read_file() success path={path} size={len(data)}")
        return data
    except Exception as e:
        logger.error(f"read_file() error path={path}: {e}", exc_info=True)
        return f"❌ 读取文件失败: {str(e)}"
