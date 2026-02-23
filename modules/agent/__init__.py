"""
modules.agent — Manus 风格的本地智能体模块包
导出：ManusAgent（核心 ReAct 智能体）、AgentTools（工具箱）、WebSurfer（浏览器能力）

所有接口均使用同步调用以便与现有主循环无缝集成。
"""

from .core import ManusAgent
from .agent_tools import AgentTools
# ``ActionExecutor`` 是旧版的底层实现类。当前代码应通过
# ``AgentTools`` 访问控制功能。
# 为了向后兼容我们仍然导出它，但在未来的版本中可能会将其移除。
# ``ActionExecutor`` 已从公共 API 移除；调用者应使用
# AgentTools 中的高层接口。如果确实需要执行器，可自行
# 实现并传入 AgentTools。
from .safety import SafetyGuard

__all__ = ["ManusAgent", "AgentTools", "SafetyGuard"]
