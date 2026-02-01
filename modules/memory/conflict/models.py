"""
冲突检测数据模型
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConflictCandidate:
    """冲突候选项"""
    doc_id: str
    document: str
    distance: float
    metadata: dict
    collection: object
    layer_name: str
    conflict_reason: str = ""


@dataclass 
class LocatedEntity:
    """定位到的实体信息"""
    entity: str              # 实体词
    weight: float            # 权重
    category: Optional[str]  # 偏好类别（如 food, music 等）
