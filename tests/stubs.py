"""
集中管理第三方可选依赖的 stub 模块。

在 conftest.py 中导入此模块，避免在多个测试文件中重复定义 stub。
"""

import sys
import types


def install_mcp_stubs() -> None:
    """安装 MCP 模块的 stub（如果未安装）。"""
    if "mcp" in sys.modules:
        return

    mcp_stub = types.ModuleType("mcp")

    class _DummyClientSession:
        pass

    class _DummyStdioServerParameters:
        def __init__(self, *args, **kwargs):
            pass

    mcp_stub.ClientSession = _DummyClientSession
    mcp_stub.StdioServerParameters = _DummyStdioServerParameters

    mcp_client = types.ModuleType("mcp.client")
    mcp_sse = types.ModuleType("mcp.client.sse")
    mcp_stdio = types.ModuleType("mcp.client.stdio")

    mcp_sse.sse_client = lambda *args, **kwargs: None
    mcp_stdio.stdio_client = lambda *args, **kwargs: None

    mcp_types = types.ModuleType("mcp.types")

    class _DummyListToolsResult:
        pass

    class _DummyTextContent:
        def __init__(self, *args, **kwargs):
            pass

    mcp_types.ListToolsResult = _DummyListToolsResult
    mcp_types.TextContent = _DummyTextContent

    sys.modules["mcp"] = mcp_stub
    sys.modules["mcp.client"] = mcp_client
    sys.modules["mcp.client.sse"] = mcp_sse
    sys.modules["mcp.client.stdio"] = mcp_stdio
    sys.modules["mcp.types"] = mcp_types


def install_loguru_stubs() -> None:
    """安装 loguru 模块的 stub（如果未安装）。"""
    if "loguru" in sys.modules:
        return

    loguru_stub = types.ModuleType("loguru")

    class _DummyLogger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def opt(self, *args, **kwargs):
            return self

        def add(self, *args, **kwargs):
            return 0

        def remove(self, *args, **kwargs):
            pass

    loguru_stub.logger = _DummyLogger()
    sys.modules["loguru"] = loguru_stub


def install_tiktoken_stubs() -> None:
    """安装 tiktoken 模块的 stub（如果未安装）。"""
    if "tiktoken" in sys.modules:
        return

    tiktoken_stub = types.ModuleType("tiktoken")

    class _DummyEncoding:
        def encode(self, text: str, *args, **kwargs) -> list[int]:
            return list(text.encode("utf-8"))

        def decode(self, tokens: list[int]) -> str:
            return bytes(tokens).decode("utf-8", errors="replace")

    def _dummy_encoding_for_model(model: str, **kwargs) -> _DummyEncoding:
        return _DummyEncoding()

    tiktoken_stub.encoding_for_model = _dummy_encoding_for_model
    tiktoken_stub.get_encoding = _dummy_encoding_for_model
    sys.modules["tiktoken"] = tiktoken_stub


def install_all_stubs() -> None:
    """安装所有可选依赖的 stub。"""
    install_mcp_stubs()
    install_loguru_stubs()
    install_tiktoken_stubs()
