"""
人类化记忆系统 - 兼容层
保持向后兼容，实际实现已迁移到 memory/ 子模块

模块结构:
modules/memory/
├── __init__.py     # 模块入口
├── config.py       # 配置参数
├── logger.py       # 日志配置  
├── analyzers.py    # 文本分析器
├── conflict.py     # 冲突检测与覆盖
├── storage.py      # 存储层
├── retrieval.py    # 检索与去重
└── core.py         # 核心记忆管理类
"""

# 从新的模块化实现导入，保持向后兼容
from .memory import HumanLikeMemory, MemoryManager

__all__ = ['HumanLikeMemory', 'MemoryManager']
