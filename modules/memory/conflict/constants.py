"""
冲突检测常量与阈值配置
"""

# 疑问句指示词
QUESTION_INDICATORS = ['吗', '呢', '吧', '?', '？', '什么', '哪', '怎么', '为什么', '还记得']

# ==================== 冲突判定阈值 ====================
EXACT_DUPLICATE_THRESHOLD = 0.15      # 极高相似度：几乎完全重复
ENTITY_CONFLICT_THRESHOLD = 0.4       # 实体级冲突阈值
PREFERENCE_CONFLICT_THRESHOLD = 0.5   # 偏好冲突阈值
SAME_CATEGORY_THRESHOLD = 1.0         # 同类偏好阈值（放宽，避免漏判）
