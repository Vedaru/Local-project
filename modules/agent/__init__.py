"""
modules.agent — 基于 OpenManus 框架的智能体模块包

核心类:
  ManusAgent — 对 OpenManus Manus agent 的同步包装，提供 run_task() 接口。

OpenManus 提供完整的异步 ToolCall Agent 架构，包含:
  - 浏览器自动化 (BrowserUseTool)
  - Python 代码执行 (PythonExecute)
  - 文件编辑 (StrReplaceEditor)
  - 网页搜索 (WebSearch / Baidu)
  - MCP 协议支持
"""

from .core import ManusAgent

__all__ = ["ManusAgent"]
