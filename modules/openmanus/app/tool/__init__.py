from __future__ import annotations

# expose only the core pieces up front. other tools are loaded lazily to
# avoid pulling in large dependency trees when a simple import occurs.
from app.tool.base import BaseTool
from app.tool.bash import Bash
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.terminate import Terminate
from app.tool.tool_collection import ToolCollection

# tools requiring extra dependencies are imported on demand
_lazy_tools: dict[str, str] = {
    "BrowserUseTool": "app.tool.browser_use_tool",
    "Crawl4aiTool": "app.tool.crawl4ai",
    "CreateChatCompletion": "app.tool.create_chat_completion",
    "PlanningTool": "app.tool.planning",
    "WebSearch": "app.tool.web_search",
}

__all__ = [
    "BaseTool",
    "Bash",
    "StrReplaceEditor",
    "Terminate",
    "ToolCollection",
] + list(_lazy_tools.keys())


def __getattr__(name: str):
    """Lazy import helper for optional tool classes.

    This is triggered when user code does ``from app.tool import BrowserUseTool``
    (or similar). Instead of importing every tool module at package import
    time, we only load the one actually requested. This keeps simple imports
    lightweight and avoids bringing in heavy third-party packages unless they
    are truly needed.
    """
    if name in _lazy_tools:
        module = __import__(_lazy_tools[name], fromlist=[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__} has no attribute {name}")


def __dir__():
    return __all__
