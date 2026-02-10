"""
安全模块 - 白名单检查
防止 AI 执行恶意操作
"""

import os
from typing import Dict
from ..logging_config import get_logger

logger = get_logger('SafetyGuard')


class SafetyGuard:
    """
    安全守卫类
    负责验证 AI 请求的操作是否安全
    """

    def __init__(self, whitelist: Dict[str, str]):
        """
        初始化安全守卫

        Args:
            whitelist: 应用白名单字典，key为别名，value为绝对路径
        """
        # 将白名单的 key 都转换为小写，方便匹配
        self.whitelist = {k.lower(): v for k, v in whitelist.items()}
        logger.info(f"安全白名单已初始化: {list(self.whitelist.keys())}")

    def validate_path(self, target: str) -> str:
        """
        验证目标应用是否在白名单内

        Args:
            target: 应用别名或路径

        Returns:
            str: 验证通过的绝对路径，如果失败则抛出异常

        Raises:
            ValueError: 如果目标不在白名单内或路径不存在
        """
        target_lower = target.lower()
        if target_lower not in self.whitelist:
            raise ValueError(f"❌ 安全警告: 应用别名 '{target}' 不在白名单内，拒绝执行。")

        path = self.whitelist[target_lower]
        logger.debug(f"验证通过: '{target}' -> '{path}'")

        if not os.path.exists(path):
            raise ValueError(f"❌ 安全警告: 应用路径 '{path}' 不存在")

        return path