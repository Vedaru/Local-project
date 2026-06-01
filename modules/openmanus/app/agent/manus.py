from typing import Dict, List, Optional

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.logger import logger
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection, WebSearch
from app.tool.ask_human import AskHuman
from app.tool.document_skill import DocumentSkillTool
from app.tool.memory_md import MemoryMarkdownTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor

BROWSER_TOOL_NAME = "browser_use"

_MCP_AVAILABLE = False
_MCP_IMPORT_ERROR = ""
MCPClients: type
MCPClientTool: type


def _load_mcp_tooling() -> bool:
    """延迟加载 MCP；未安装 mcp 包时 Manus 仍可运行（仅无 MCP 远程工具）。"""
    global _MCP_AVAILABLE, _MCP_IMPORT_ERROR, MCPClients, MCPClientTool
    if _MCP_AVAILABLE:
        return True
    try:
        from app.tool.mcp import MCPClients as _MCPClients
        from app.tool.mcp import MCPClientTool as _MCPClientTool

        MCPClients = _MCPClients
        MCPClientTool = _MCPClientTool
        _MCP_AVAILABLE = True
        _MCP_IMPORT_ERROR = ""
        return True
    except ImportError as exc:
        _MCP_AVAILABLE = False
        _MCP_IMPORT_ERROR = str(exc)

        class _MCPClientsStub:
            tools: list = []

            async def connect_stdio(self, *args, **kwargs):
                return None

            async def connect_sse(self, *args, **kwargs):
                return None

            async def disconnect(self, server_id: str = ""):
                return None

        class _MCPClientToolStub:
            server_id: str = ""

        MCPClients = _MCPClientsStub  # type: ignore[misc, assignment]
        MCPClientTool = _MCPClientToolStub  # type: ignore[misc, assignment]
        logger.warning("mcp 未安装，Manus 将以无 MCP 远程工具模式运行: %s", exc)
        return False


_load_mcp_tooling()


def _default_mcp_clients():
    return MCPClients()


def _format_allowed_directories() -> str:
    """Format configured local workspace roots for prompt injection."""
    return "\n".join(f"- {path.absolute()}" for path in config.workspace_roots)


def _build_manus_tool_collection() -> ToolCollection:
    """Assemble Manus tools; omit browser automation when browser_use is not installed."""
    tools = [
        DocumentSkillTool(),
        PythonExecute(),
        WebSearch(),
        StrReplaceEditor(),
        MemoryMarkdownTool(),
        AskHuman(),
        Terminate(),
    ]
    try:
        from modules.security_tools import is_tool_allowed

        if is_tool_allowed(BROWSER_TOOL_NAME):
            from app.tool.browser_use_tool import BrowserUseTool

            tools.insert(3, BrowserUseTool())
    except ImportError:
        logger.warning("browser_use 未安装，Manus 将以无浏览器模式运行（WebSearch 仍可用）")
    except Exception as exc:
        logger.warning("BrowserUseTool 加载失败，已跳过: %s", exc)
    return ToolCollection(*tools)


class Manus(ToolCallAgent):
    """A versatile general-purpose agent with support for both local and MCP tools."""

    name: str = "Manus"
    description: str = "A versatile agent that can solve various tasks using multiple tools including MCP-based tools"

    system_prompt: str = SYSTEM_PROMPT.format(
        directory=config.workspace_root.absolute(),
        allowed_directories=_format_allowed_directories(),
    )
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 10000
    max_steps: int = 100

    # MCP clients for remote tool access（mcp 包缺失时为 stub）
    mcp_clients: MCPClients = Field(default_factory=_default_mcp_clients)

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(default_factory=_build_manus_tool_collection)

    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])
    browser_context_helper: Optional[BrowserContextHelper] = None

    # Track connected MCP servers
    connected_servers: Dict[str, str] = Field(
        default_factory=dict
    )  # server_id -> url/command
    _initialized: bool = False

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        """Initialize basic components synchronously."""
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    @classmethod
    async def create(cls, **kwargs) -> "Manus":
        """Factory method to create and properly initialize a Manus instance."""
        instance = cls(**kwargs)
        await instance.initialize_mcp_servers()
        instance._initialized = True
        return instance

    async def initialize_mcp_servers(self) -> None:
        """Initialize connections to configured MCP servers."""
        if not _load_mcp_tooling():
            return
        for server_id, server_config in config.mcp_config.servers.items():
            try:
                if server_config.type == "sse":
                    if server_config.url:
                        await self.connect_mcp_server(server_config.url, server_id)
                        logger.info(
                            f"Connected to MCP server {server_id} at {server_config.url}"
                        )
                elif server_config.type == "stdio":
                    if server_config.command:
                        await self.connect_mcp_server(
                            server_config.command,
                            server_id,
                            use_stdio=True,
                            stdio_args=server_config.args,
                        )
                        logger.info(
                            f"Connected to MCP server {server_id} using command {server_config.command}"
                        )
            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server_id}: {e}")

    async def connect_mcp_server(
        self,
        server_url: str,
        server_id: str = "",
        use_stdio: bool = False,
        stdio_args: List[str] = None,
    ) -> None:
        """Connect to an MCP server and add its tools."""
        if not _MCP_AVAILABLE:
            logger.debug("跳过 MCP 连接（mcp 包未安装）")
            return
        if use_stdio:
            await self.mcp_clients.connect_stdio(
                server_url, stdio_args or [], server_id
            )
            self.connected_servers[server_id or server_url] = server_url
        else:
            await self.mcp_clients.connect_sse(server_url, server_id)
            self.connected_servers[server_id or server_url] = server_url

        # Update available tools with only the new tools from this server
        new_tools = [
            tool for tool in self.mcp_clients.tools if tool.server_id == server_id
        ]
        self.available_tools.add_tools(*new_tools)

    async def disconnect_mcp_server(self, server_id: str = "") -> None:
        """Disconnect from an MCP server and remove its tools."""
        if not _MCP_AVAILABLE:
            return
        await self.mcp_clients.disconnect(server_id)
        if server_id:
            self.connected_servers.pop(server_id, None)
        else:
            self.connected_servers.clear()

        # Rebuild available tools without the disconnected server's tools
        base_tools = [
            tool
            for tool in self.available_tools.tools
            if not isinstance(tool, MCPClientTool)
        ]
        self.available_tools = ToolCollection(*base_tools)
        self.available_tools.add_tools(*self.mcp_clients.tools)

    async def cleanup(self):
        """Clean up Manus agent resources."""
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
        # Disconnect from all MCP servers only if we were initialized
        if self._initialized:
            await self.disconnect_mcp_server()
            self._initialized = False

    async def think(self) -> bool:
        """Process current state and decide next actions with appropriate context."""
        if not self._initialized:
            await self.initialize_mcp_servers()
            self._initialized = True

        original_prompt = self.next_step_prompt
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []
        browser_in_use = any(
            tc.function.name == BROWSER_TOOL_NAME
            for msg in recent_messages
            if msg.tool_calls
            for tc in msg.tool_calls
        )

        if browser_in_use and self.browser_context_helper:
            self.next_step_prompt = (
                await self.browser_context_helper.format_next_step_prompt()
            )

        result = await super().think()

        # Restore original prompt
        self.next_step_prompt = original_prompt

        return result
