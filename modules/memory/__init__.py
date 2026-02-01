"""
人类化记忆系统 - 模块化版本

模块结构:
- config.py: 配置参数和常量
- logger.py: 日志配置
- analyzers.py: 文本分析器（实体提取、情感分析等）
- conflict.py: 冲突检测与覆盖
- storage.py: 存储层（ChromaDB交互）
- retrieval.py: 检索与去重
- core.py: 核心记忆管理类
"""

from .core import HumanLikeMemory, MemoryManager

__all__ = ['HumanLikeMemory', 'MemoryManager']
