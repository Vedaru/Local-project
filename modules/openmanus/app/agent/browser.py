import json
from typing import TYPE_CHECKING, Optional

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.browser import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import Message, ToolChoice
from app.tool import Terminate, ToolCollection

BROWSER_USE_TOOL_NAME = "browser_use"


# Avoid circular import if BrowserAgent needs BrowserContextHelper
if TYPE_CHECKING:
    from app.agent.base import BaseAgent  # Or wherever memory is defined


class BrowserContextHelper:
    def __init__(self, agent: "BaseAgent"):
        self.agent = agent
        self._current_base64_image: Optional[str] = None

    @staticmethod
    def _build_prompt_preview(text: str, max_chars: int = 2200) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text

        head_chars = max_chars // 2
        tail_chars = max_chars - head_chars
        omitted = len(text) - max_chars
        return (
            f"{text[:head_chars]} "
            f"...[{omitted} chars omitted]... "
            f"{text[-tail_chars:]}"
        )

    async def get_browser_state(self) -> Optional[dict]:
        browser_tool = self.agent.available_tools.get_tool(BROWSER_USE_TOOL_NAME)
        if not browser_tool:
            try:
                sandbox_module = __import__(
                    "app.tool.sandbox.sb_browser_tool",
                    fromlist=["SandboxBrowserTool"],
                )
                sandbox_tool_cls = getattr(sandbox_module, "SandboxBrowserTool", None)
                if sandbox_tool_cls:
                    browser_tool = self.agent.available_tools.get_tool(
                        sandbox_tool_cls().name
                    )
            except Exception:
                pass
        if not browser_tool or not hasattr(browser_tool, "get_current_state"):
            logger.warning("BrowserUseTool not found or doesn't have get_current_state")
            return None
        try:
            result = await browser_tool.get_current_state()
            if result.error:
                logger.debug(f"Browser state error: {result.error}")
                return None
            if hasattr(result, "base64_image") and result.base64_image:
                self._current_base64_image = result.base64_image
            else:
                self._current_base64_image = None
            return json.loads(result.output)
        except Exception as e:
            logger.debug(f"Failed to get browser state: {str(e)}")
            return None

    async def format_next_step_prompt(self) -> str:
        """Gets browser state and formats the browser prompt."""
        browser_state = await self.get_browser_state()
        url_info, tabs_info, content_above_info, content_below_info = "", "", "", ""
        results_info = ""  # Or get from agent if needed elsewhere

        if browser_state and not browser_state.get("error"):
            url_info = f"\n   URL: {browser_state.get('url', 'N/A')}\n   Title: {browser_state.get('title', 'N/A')}"
            tabs = browser_state.get("tabs", [])
            if tabs:
                tab_lines = [f"\n   {len(tabs)} tab(s) available"]
                for tab in tabs[:8]:
                    if not isinstance(tab, dict):
                        continue
                    tab_lines.append(
                        "\n   - "
                        f"index={tab.get('index', '?')}, "
                        f"id={tab.get('id', 'N/A')}, "
                        f"title={str(tab.get('title') or '(untitled)')[:80]}, "
                        f"url={str(tab.get('url') or '(no-url)')[:120]}"
                    )
                if len(tabs) > 8:
                    tab_lines.append(f"\n   - ... and {len(tabs) - 8} more tabs")
                tabs_info = "".join(tab_lines)
            scroll_info = browser_state.get("scroll_info", {})
            if not isinstance(scroll_info, dict):
                scroll_info = {}
            pixels_above = scroll_info.get("pixels_above", 0)
            pixels_below = scroll_info.get("pixels_below", 0)
            if pixels_above > 0:
                content_above_info = f" ({pixels_above} pixels)"
            if pixels_below > 0:
                content_below_info = f" ({pixels_below} pixels)"

            viewport_text = browser_state.get("viewport_text")
            viewport_text_length = browser_state.get("viewport_text_length", 0)
            if viewport_text:
                viewport_snippet = viewport_text.replace("\n", " ")
                viewport_snippet = self._build_prompt_preview(
                    viewport_snippet,
                    max_chars=2200,
                )
                if viewport_text_length:
                    results_info += (
                        f"\n   Visible viewport text ({viewport_text_length} chars total): "
                        f"{viewport_snippet}"
                    )
                else:
                    results_info += (
                        f"\n   Visible viewport text: {viewport_snippet}"
                    )

            # include full-page text summary as additional context
            page_text = browser_state.get("page_text")
            page_text_length = browser_state.get("page_text_length", 0)
            if page_text:
                snippet = page_text.replace("\n", " ")
                snippet = self._build_prompt_preview(snippet, max_chars=2200)
                if page_text_length:
                    results_info += (
                        f"\n   Full-page text preview ({page_text_length} chars total): "
                        f"{snippet}"
                    )
                else:
                    results_info += f"\n   Full-page text preview: {snippet}"

            if self._current_base64_image:
                image_message = Message.user_message(
                    content="Current browser screenshot:",
                    base64_image=self._current_base64_image,
                )
                self.agent.memory.add_message(image_message)
                self._current_base64_image = None  # Consume the image after adding

        return NEXT_STEP_PROMPT.format(
            url_placeholder=url_info,
            tabs_placeholder=tabs_info,
            content_above_placeholder=content_above_info,
            content_below_placeholder=content_below_info,
            results_placeholder=results_info,
        )

    async def cleanup_browser(self):
        browser_tool = self.agent.available_tools.get_tool(BROWSER_USE_TOOL_NAME)
        if browser_tool and hasattr(browser_tool, "cleanup"):
            await browser_tool.cleanup()


def _build_browser_agent_tools() -> ToolCollection:
    try:
        from app.tool.browser_use_tool import BrowserUseTool

        return ToolCollection(BrowserUseTool(), Terminate())
    except ImportError:
        logger.warning("browser_use 未安装，BrowserAgent 仅保留 Terminate 工具")
        return ToolCollection(Terminate())


class BrowserAgent(ToolCallAgent):
    """
    A browser agent that uses the browser_use library to control a browser.

    This agent can navigate web pages, interact with elements, fill forms,
    extract content, and perform other browser-based actions to accomplish tasks.
    """

    name: str = "browser"
    description: str = "A browser agent that can control a browser to accomplish tasks"

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 10000
    max_steps: int = 100

    # Configure the available tools
    available_tools: ToolCollection = Field(default_factory=_build_browser_agent_tools)

    # Use Auto for tool choice to allow both tool usage and free-form responses
    tool_choices: ToolChoice = ToolChoice.AUTO
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    browser_context_helper: Optional[BrowserContextHelper] = None

    @model_validator(mode="after")
    def initialize_helper(self) -> "BrowserAgent":
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    async def think(self) -> bool:
        """Process current state and decide next actions using tools, with browser state info added"""
        self.next_step_prompt = (
            await self.browser_context_helper.format_next_step_prompt()
        )
        return await super().think()

    async def cleanup(self):
        """Clean up browser agent resources by calling parent cleanup."""
        await self.browser_context_helper.cleanup_browser()
