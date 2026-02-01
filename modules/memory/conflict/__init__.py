"""
冲突检测与覆盖模块

核心流程（四步法）：
1. 定位 (Entity Extraction) - 提取核心实体关键词
2. 检索 (Query) - 基于实体检索相关旧记忆
3. 判定 (Conflict Judgment) - 语义距离 + 冲突规则判定
4. 覆盖 (Delete & Add) - 物理删除旧记忆，插入新记录

模块结构：
- constants.py  : 阈值与常量配置
- models.py     : 数据模型 (ConflictCandidate, LocatedEntity)
- utils.py      : 辅助函数
- locator.py    : EntityLocator - Step 1 实体定位
- detector.py   : ConflictDetector - Step 3 冲突判定
- resolver.py   : ConflictResolver - Step 2 & 4 检索与覆盖
"""

from .constants import (
    QUESTION_INDICATORS,
    EXACT_DUPLICATE_THRESHOLD,
    ENTITY_CONFLICT_THRESHOLD,
    PREFERENCE_CONFLICT_THRESHOLD,
    SAME_CATEGORY_THRESHOLD
)
from .models import ConflictCandidate, LocatedEntity
from .utils import extract_user_input, is_question
from .locator import EntityLocator
from .detector import ConflictDetector
from .resolver import ConflictResolver

__all__ = [
    # Constants
    'QUESTION_INDICATORS',
    'EXACT_DUPLICATE_THRESHOLD',
    'ENTITY_CONFLICT_THRESHOLD',
    'PREFERENCE_CONFLICT_THRESHOLD',
    'SAME_CATEGORY_THRESHOLD',
    # Models
    'ConflictCandidate',
    'LocatedEntity',
    # Utils
    'extract_user_input',
    'is_question',
    # Classes
    'EntityLocator',
    'ConflictDetector',
    'ConflictResolver',
]
