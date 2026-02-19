"""
modules.agent — Manus 风格的本地智能体模块包
导出：ManusAgent（核心 ReAct 智能体）、AgentTools（工具箱）、WebSurfer（浏览器能力）

所有接口均使用同步调用以便与现有主循环无缝集成。
"""

from .core import ManusAgent
from .tools import AgentTools
from .browser import WebSurfer
from .controller import ComputerController
from .executor import ActionExecutor
from .safety import SafetyGuard

__all__ = ["ManusAgent", "AgentTools", "WebSurfer", "ComputerController", "ActionExecutor", "SafetyGuard"]
