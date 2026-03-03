"""
记忆系统 — 基于 memoripy 的实现

模块结构:
- memoripy/: memoripy 核心库 (FAISS, 概念图, 语义聚类)
- models.py: 模型适配器 (ArkChatModel, LocalEmbeddingModel)
- wrapper.py: MemoryManager 包装器 (提供与旧代码兼容的接口)
- skills.py: 技能管理器 (SkillManager, ChromaDB)
"""

from .wrapper import MemoryManager
from .skills import SkillManager

__all__ = ['MemoryManager', 'SkillManager']
