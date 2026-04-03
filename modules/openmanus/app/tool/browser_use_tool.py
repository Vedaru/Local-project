import asyncio
from typing import Generic, Optional, TypeVar

from browser_use import Browser as BrowserUseBrowser
from browser_use import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.dom.service import DomService
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config import config
from app.llm import LLM
from app.tool.base import BaseTool, ToolResult
from app.tool.browser_use_tool_actions import (
    handle_click_element_action,
    handle_click_text_action,
    handle_interaction_action,
    handle_navigation_action,
    handle_tab_action,
    handle_utility_action,
)
from app.tool.browser_use_tool_content import (
    build_extraction_function_schema,
    extract_chunk_with_llm,
    get_current_state,
    get_max_content_length,
    get_media_status,
    handle_extract_content_action,
)
from app.tool.browser_use_tool_state_helpers import (
    auto_switch_to_new_tab_if_needed,
    build_click_feedback,
    build_text_preview,
    format_tabs_for_output,
    get_browser_state_compatible,
    get_element_brief_by_xpath,
    get_page_summary,
    get_tabs_info,
    has_meaningful_page_change,
    is_home_label,
    normalize_tabs,
    normalize_url,
    predict_click_effect,
    prepare_dom_index_cache,
    resolve_tab_switch_index,
    split_text_into_chunks,
    switch_to_tab_index_compatible,
    trim_text,
)
from app.tool.browser_text_extractor import (
    extract_markdown_text,
    extract_page_text,
    extract_viewport_text,
    html_to_text_fallback,
    normalize_whitespace_text,
    select_preferred_page_text,
)
from app.tool.web_search import WebSearch


_BROWSER_DESCRIPTION = """\
A powerful browser automation tool that allows interaction with web pages through various actions.
* This tool provides commands for controlling a browser session, navigating web pages, and extracting information
* It maintains state across calls, keeping the browser session alive until explicitly closed
* Use this when you need to browse websites, fill forms, click buttons, extract content, or perform web searches
* Each action requires specific parameters as defined in the tool's dependencies

Key capabilities include:
* Navigation: Go to specific URLs, go back, search the web, or refresh pages
* Interaction: Inspect elements, click elements, input text, select from dropdowns, send keyboard commands
* Scrolling: Scroll up/down by pixel amount or scroll to specific text
* Content extraction: Extract and analyze content from web pages based on specific goals
* Tab management: List tabs, switch between tabs, open new tabs, or close tabs
* Media detection: Use 'get_media_status' to check if video/audio is playing on the page
* Browser lifecycle: The browser stays open after task completion by default. Use 'close_browser' to explicitly close it when you decide the browser is no longer needed.

Note: When using element indices, refer to the numbered elements shown in the current browser state.
"""

Context = TypeVar("Context")

_NAVIGATION_ACTIONS = frozenset({"go_to_url", "go_back", "refresh", "web_search", "inspect_element"})
_INTERACTION_ACTIONS = frozenset(
    {
        "input_text",
        "scroll_down",
        "scroll_up",
        "scroll_to_text",
        "send_keys",
        "get_dropdown_options",
        "select_dropdown_option",
    }
)
_TAB_ACTIONS = frozenset({"switch_tab", "list_tabs", "open_tab", "close_tab"})
_UTILITY_ACTIONS = frozenset({"wait", "get_media_status", "close_browser"})


class BrowserUseTool(BaseTool, Generic[Context]):
    name: str = "browser_use"
    description: str = _BROWSER_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url",
                    "refresh",
                    "inspect_element",
                    "click_element",
                    "click_text",
                    "input_text",
                    "scroll_down",
                    "scroll_up",
                    "scroll_to_text",
                    "send_keys",
                    "get_dropdown_options",
                    "select_dropdown_option",
                    "go_back",
                    "web_search",
                    "wait",
                    "extract_content",
                    "switch_tab",
                    "list_tabs",
                    "open_tab",
                    "close_tab",
                    "get_media_status",
                    "close_browser",
                ],
                "description": "The browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL for 'go_to_url' or 'open_tab' actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click_element', 'input_text', 'get_dropdown_options', or 'select_dropdown_option' actions",
            },
            "text": {
                "type": "string",
                "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll_down' or 'scroll_up' actions",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action",
            },
            "query": {
                "type": "string",
                "description": "Search query for 'web_search' action",
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for 'extract_content' action",
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for 'send_keys' action",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for 'wait' action",
            },
        },
        "required": ["action"],
        "dependencies": {
            "go_to_url": ["url"],
            "inspect_element": ["index"],
            "click_element": ["index"],
            "input_text": ["index", "text"],
            "switch_tab": ["tab_id"],
            "open_tab": ["url"],
            "click_text": ["text"],
            "scroll_down": ["scroll_amount"],
            "scroll_up": ["scroll_amount"],
            "scroll_to_text": ["text"],
            "send_keys": ["keys"],
            "get_dropdown_options": ["index"],
            "select_dropdown_option": ["index", "text"],
            "go_back": [],
            "refresh": [],
            "web_search": ["query"],
            "wait": ["seconds"],
            "extract_content": ["goal"],
            "list_tabs": [],
            "close_tab": [],
            "get_media_status": [],
            "close_browser": [],
        },
    }

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)
    browser: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)
    context: Optional[BrowserContext] = Field(default=None, exclude=True)
    dom_service: Optional[DomService] = Field(default=None, exclude=True)
    web_search_tool: WebSearch = Field(default_factory=WebSearch, exclude=True)

    # Context for generic functionality
    tool_context: Optional[Context] = Field(default=None, exclude=True)

    # Flag to keep browser open after task completion (default: True)
    # Agent can explicitly close browser via close_browser action
    keep_browser_open: bool = Field(default=True, exclude=True)

    llm: Optional[LLM] = Field(default_factory=LLM)

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        if not v:
            raise ValueError("Parameters cannot be empty")
        return v

    _get_browser_state_compatible = get_browser_state_compatible
    _prepare_dom_index_cache = prepare_dom_index_cache
    _trim_text = staticmethod(trim_text)
    _normalize_url = staticmethod(normalize_url)
    _is_home_label = staticmethod(is_home_label)
    _has_meaningful_page_change = staticmethod(has_meaningful_page_change)
    _build_click_feedback = staticmethod(build_click_feedback)
    _predict_click_effect = staticmethod(predict_click_effect)
    _get_page_summary = get_page_summary
    _get_element_brief_by_xpath = get_element_brief_by_xpath
    _normalize_tabs = staticmethod(normalize_tabs)
    _format_tabs_for_output = staticmethod(format_tabs_for_output)
    _get_tabs_info = get_tabs_info
    _resolve_tab_switch_index = staticmethod(resolve_tab_switch_index)
    _switch_to_tab_index_compatible = switch_to_tab_index_compatible
    _auto_switch_to_new_tab_if_needed = auto_switch_to_new_tab_if_needed
    _split_text_into_chunks = staticmethod(split_text_into_chunks)
    _build_text_preview = staticmethod(build_text_preview)

    _normalize_whitespace_text = staticmethod(normalize_whitespace_text)
    _html_to_text_fallback = staticmethod(html_to_text_fallback)
    _extract_markdown_text = staticmethod(extract_markdown_text)
    _select_preferred_page_text = staticmethod(select_preferred_page_text)
    _extract_page_text = staticmethod(extract_page_text)
    _extract_viewport_text = staticmethod(extract_viewport_text)

    _build_extraction_function_schema = staticmethod(build_extraction_function_schema)
    _get_max_content_length = get_max_content_length
    _extract_chunk_with_llm = extract_chunk_with_llm

    async def _ensure_browser_initialized(self) -> BrowserContext:
        """Ensure browser and context are initialized."""
        if self.browser is None:
            browser_config_kwargs = {"headless": False, "disable_security": True}

            if config.browser_config:
                from browser_use.browser.browser import ProxySettings

                # handle proxy settings.
                if config.browser_config.proxy and config.browser_config.proxy.server:
                    browser_config_kwargs["proxy"] = ProxySettings(
                        server=config.browser_config.proxy.server,
                        username=config.browser_config.proxy.username,
                        password=config.browser_config.proxy.password,
                    )

                browser_attrs = [
                    "headless",
                    "disable_security",
                    "extra_chromium_args",
                    "chrome_instance_path",
                    "wss_url",
                    "cdp_url",
                ]

                for attr in browser_attrs:
                    value = getattr(config.browser_config, attr, None)
                    if value is not None:
                        if not isinstance(value, list) or value:
                            browser_config_kwargs[attr] = value

            self.browser = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))

        if self.context is None:
            context_config = BrowserContextConfig()

            # if there is context config in the config, use it.
            if (
                config.browser_config
                and hasattr(config.browser_config, "new_context_config")
                and config.browser_config.new_context_config
            ):
                context_config = config.browser_config.new_context_config

            self.context = await self.browser.new_context(context_config)
            self.dom_service = DomService(await self.context.get_current_page())

        return self.context

    _handle_click_element_action = handle_click_element_action
    _handle_click_text_action = handle_click_text_action
    _handle_interaction_action = handle_interaction_action
    _handle_extract_content_action = handle_extract_content_action
    _handle_navigation_action = handle_navigation_action
    _handle_tab_action = handle_tab_action
    _handle_utility_action = handle_utility_action

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        query: Optional[str] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a specified browser action.

        Args:
            action: The browser action to perform
            url: URL for navigation or new tab
            index: Element index for click or input actions
            text: Text for input action or search query
            scroll_amount: Pixels to scroll for scroll action
            tab_id: Tab ID for switch_tab action
            query: Search query for Google search
            goal: Extraction goal for content extraction
            keys: Keys to send for keyboard actions
            seconds: Seconds to wait
            **kwargs: Additional arguments

        Returns:
            ToolResult with the action's output or error
        """
        async with self.lock:
            try:
                context = await self._ensure_browser_initialized()

                # Get max content length from config
                max_content_length = self._get_max_content_length()

                # Navigation actions
                if action in _NAVIGATION_ACTIONS:
                    navigation_result = await self._handle_navigation_action(
                        context,
                        action,
                        url,
                        query,
                        index,
                    )
                    if navigation_result is not None:
                        return navigation_result

                # Element interaction actions
                elif action == "click_element":
                    return await self._handle_click_element_action(context, index)

                elif action == "click_text":
                    return await self._handle_click_text_action(context, text)

                elif action in _INTERACTION_ACTIONS:
                    interaction_result = await self._handle_interaction_action(
                        context,
                        action,
                        index,
                        text,
                        scroll_amount,
                        keys,
                    )
                    if interaction_result is not None:
                        return interaction_result
                    return ToolResult(error=f"Unknown interaction action: {action}")

                # Content extraction actions
                elif action == "extract_content":
                    return await self._handle_extract_content_action(
                        context,
                        goal,
                        max_content_length,
                    )

                # Tab management actions
                if action in _TAB_ACTIONS:
                    tab_result = await self._handle_tab_action(
                        context,
                        action,
                        tab_id,
                        url,
                    )
                    if tab_result is not None:
                        return tab_result

                # Utility actions
                if action in _UTILITY_ACTIONS:
                    utility_result = await self._handle_utility_action(
                        context,
                        action,
                        seconds,
                    )
                    if utility_result is not None:
                        return utility_result

                return ToolResult(error=f"Unknown action: {action}")

            except Exception as e:
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")

    _get_media_status = get_media_status
    get_current_state = get_current_state

    async def _force_cleanup(self):
        """Unconditionally close browser resources."""
        async with self.lock:
            if self.context is not None:
                await self.context.close()
                self.context = None
                self.dom_service = None
            if self.browser is not None:
                await self.browser.close()
                self.browser = None

    async def cleanup(self):
        """Clean up browser resources. Respects keep_browser_open flag."""
        if self.keep_browser_open:
            return
        await self._force_cleanup()

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """Factory method to create a BrowserUseTool with a specific context."""
        tool = cls()
        tool.tool_context = context
        return tool
