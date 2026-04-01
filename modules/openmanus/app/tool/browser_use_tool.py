import asyncio
import base64
import json
from typing import Any, Generic, Optional, TypeVar
from urllib.parse import urlparse

from browser_use import Browser as BrowserUseBrowser
from browser_use import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.dom.service import DomService
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config import config
from app.llm import LLM
from app.tool.base import BaseTool, ToolResult
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

    async def _get_browser_state_compatible(self, ctx: BrowserContext):
        """Get browser state with compatibility across browser_use versions.

        Newer versions require `cache_clickable_elements_hashes` while older versions
        accept no arguments.
        """
        try:
            return await ctx.get_state(cache_clickable_elements_hashes=True)
        except TypeError:
            try:
                return await ctx.get_state(True)
            except TypeError:
                return await ctx.get_state()

    async def _prepare_dom_index_cache(self, ctx: BrowserContext) -> None:
        """Prime browser_use's clickable-element cache before index-based actions."""
        await self._get_browser_state_compatible(ctx)

    @staticmethod
    def _trim_text(value: Any, max_len: int = 120) -> str:
        text = str(value or "").strip().replace("\n", " ")
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    @staticmethod
    def _normalize_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url or "")
        host = (parsed.netloc or "").lower()
        path = parsed.path or "/"
        normalized_path = path.rstrip("/") or "/"
        return host, normalized_path

    @staticmethod
    def _is_home_label(text: str) -> bool:
        normalized = (text or "").strip().lower()
        return normalized in {
            "home",
            "首页",
            "主页",
            "main",
        }

    @staticmethod
    def _has_meaningful_page_change(
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> bool:
        before_host, before_path = BrowserUseTool._normalize_url(
            str(before_summary.get("url") or "")
        )
        after_host, after_path = BrowserUseTool._normalize_url(
            str(after_summary.get("url") or "")
        )
        if before_host != after_host or before_path != after_path:
            return True

        return int(before_summary.get("tab_count") or 0) != int(
            after_summary.get("tab_count") or 0
        )

    @staticmethod
    def _build_click_feedback(
        *,
        clicked_by: str,
        clicked_value: Any,
        element_brief: dict[str, str],
        pre_click_prediction: Optional[dict[str, Any]],
        switched_tab: Optional[dict[str, Any]],
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> dict[str, Any]:
        before_url = str(before_summary.get("url") or "")
        after_url = str(after_summary.get("url") or "")
        element_text = str(element_brief.get("text") or "")
        element_href = str(element_brief.get("href") or "")

        before_host, before_path = BrowserUseTool._normalize_url(before_url)
        after_host, after_path = BrowserUseTool._normalize_url(after_url)
        href_host, href_path = BrowserUseTool._normalize_url(element_href)

        page_changed = BrowserUseTool._has_meaningful_page_change(
            before_summary, after_summary
        )

        is_home_nav = (
            BrowserUseTool._is_home_label(element_text)
            and href_path == "/"
            and bool(href_host)
            and (not before_host or href_host == before_host)
        )

        likely_misclick = bool(
            is_home_nav and before_path != "/" and after_path == "/"
        )

        no_progress = bool(
            not page_changed
            and not switched_tab
            and not element_href
            and element_brief.get("tag") in {"div", "li", "span", ""}
        )

        if likely_misclick:
            outcome = "likely_misclick"
            recommendation = (
                "This click likely navigated to a global home entry. "
                "Avoid repeating low-index/nav clicks; return to target page and select a content-level item."
            )
        elif no_progress:
            outcome = "no_progress"
            recommendation = (
                "Click did not produce meaningful navigation. "
                "Use text-based click, scroll, or inspect tabs/elements before the next click."
            )
        elif page_changed or switched_tab:
            outcome = "progress"
            recommendation = "Progress detected. Continue from current page state."
        else:
            outcome = "uncertain"
            recommendation = "Outcome is uncertain; verify with list_tabs/extract_content/get_media_status before next step."

        return {
            "clicked_by": clicked_by,
            "clicked_value": clicked_value,
            "element": element_brief,
            "pre_click_prediction": pre_click_prediction or {},
            "transition": {
                "before_url": before_url,
                "after_url": after_url,
                "switched_tab": bool(switched_tab),
                "page_changed": page_changed,
            },
            "signals": {
                "is_home_nav": is_home_nav,
                "no_progress": no_progress,
                "likely_misclick": likely_misclick,
            },
            "outcome": outcome,
            "recommendation": recommendation,
        }

    @staticmethod
    def _predict_click_effect(
        current_url: str,
        element_brief: dict[str, str],
    ) -> dict[str, Any]:
        href = str(element_brief.get("href") or "")
        target = str(element_brief.get("target") or "").lower()
        tag = str(element_brief.get("tag") or "").lower()
        text = str(element_brief.get("text") or "")

        current_host, current_path = BrowserUseTool._normalize_url(current_url)
        href_host, href_path = BrowserUseTool._normalize_url(href)

        opens_new_tab = target in {"_blank", "blank"}
        has_link = bool(href)
        same_domain = bool(has_link and current_host and href_host == current_host)
        same_path = bool(has_link and href_host == current_host and href_path == current_path)

        if has_link and not same_path:
            likely_effect = "navigate"
        elif has_link and same_path:
            likely_effect = "same_page_or_filter_update"
        elif tag in {"button", "input"}:
            likely_effect = "in_page_interaction"
        elif tag in {"div", "li", "span", ""} and not text.strip():
            likely_effect = "low_confidence_click_target"
        else:
            likely_effect = "uncertain"

        return {
            "likely_effect": likely_effect,
            "has_link": has_link,
            "link_url": href,
            "same_domain": same_domain,
            "same_path": same_path,
            "opens_new_tab": opens_new_tab,
            "is_home_navigation": bool(
                BrowserUseTool._is_home_label(text) and href_path == "/"
            ),
        }

    async def _get_page_summary(self, ctx: BrowserContext) -> dict[str, Any]:
        page = await ctx.get_current_page()
        title = ""
        try:
            title = await page.title()
        except Exception:
            title = ""

        tabs_info = []
        try:
            tabs_info = await self._get_tabs_info(ctx)
        except Exception:
            tabs_info = []

        return {
            "url": str(getattr(page, "url", "") or ""),
            "title": self._trim_text(title, 100),
            "tab_count": len(tabs_info),
        }

    async def _get_element_brief_by_xpath(
        self,
        page,
        xpath: Optional[str],
    ) -> dict[str, str]:
        if not xpath:
            return {}

        script = """
(xPath) => {
  const node = document.evaluate(
    xPath,
    document,
    null,
    XPathResult.FIRST_ORDERED_NODE_TYPE,
    null
  ).singleNodeValue;

  if (!node) {
    return {};
  }

  const tag = (node.tagName || '').toLowerCase();
  const rawText = (node.innerText || node.textContent || '').trim();
  const text = rawText.replace(/\s+/g, ' ').slice(0, 120);

  let href = '';
  if (node.href) {
    href = node.href;
  } else {
    const anchor = node.closest && node.closest('a');
    if (anchor && anchor.href) {
      href = anchor.href;
    }
  }

  const target = node.getAttribute ? (node.getAttribute('target') || '') : '';
    const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
    const ariaLabel = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
    const className = typeof node.className === 'string' ? node.className : '';
    const id = node.id || '';
    const rect = node.getBoundingClientRect();

    return {
        tag,
        text,
        href,
        target,
        role,
        aria_label: ariaLabel,
        class_name: className,
        id,
        rect: {
            x: Math.round(rect.x || 0),
            y: Math.round(rect.y || 0),
            width: Math.round(rect.width || 0),
            height: Math.round(rect.height || 0)
        }
    };
}
"""

        try:
            result = await page.evaluate(script, xpath)
            if isinstance(result, dict):
                return {
                    "tag": self._trim_text(result.get("tag"), 30),
                    "text": self._trim_text(result.get("text"), 120),
                    "href": self._trim_text(result.get("href"), 180),
                    "target": self._trim_text(result.get("target"), 20),
                    "role": self._trim_text(result.get("role"), 30),
                    "aria_label": self._trim_text(result.get("aria_label"), 120),
                    "class_name": self._trim_text(result.get("class_name"), 120),
                    "id": self._trim_text(result.get("id"), 60),
                    "rect": result.get("rect") if isinstance(result.get("rect"), dict) else {},
                }
        except Exception:
            pass

        return {}

    @staticmethod
    def _normalize_tabs(tabs: list[Any]) -> list[dict[str, Any]]:
        """Normalize raw tab objects to stable index/id/title/url records."""
        normalized: list[dict[str, Any]] = []
        for idx, tab in enumerate(tabs or []):
            if hasattr(tab, "model_dump"):
                raw = tab.model_dump()
            elif isinstance(tab, dict):
                raw = dict(tab)
            else:
                raw = {}

            tab_id: Optional[int] = None
            for key in ("id", "tab_id", "page_id"):
                candidate = raw.get(key)
                if isinstance(candidate, int):
                    tab_id = candidate
                    break

            normalized.append(
                {
                    "index": idx,
                    "id": tab_id,
                    "title": str(raw.get("title") or ""),
                    "url": str(raw.get("url") or ""),
                }
            )
        return normalized

    @staticmethod
    def _format_tabs_for_output(tabs_info: list[dict[str, Any]]) -> str:
        if not tabs_info:
            return "No tabs available."

        lines = ["Available tabs:"]
        for tab in tabs_info:
            title = tab.get("title") or "(untitled)"
            url = tab.get("url") or "(no-url)"
            tab_id = tab.get("id")
            lines.append(
                "- "
                f"index={tab.get('index')}, "
                f"id={tab_id if tab_id is not None else 'N/A'}, "
                f"title={title}, "
                f"url={url}"
            )
        return "\n".join(lines)

    async def _get_tabs_info(self, ctx: BrowserContext) -> list[dict[str, Any]]:
        state = await self._get_browser_state_compatible(ctx)
        tabs = getattr(state, "tabs", []) or []
        return self._normalize_tabs(tabs)

    @staticmethod
    def _resolve_tab_switch_index(
        tabs_info: list[dict[str, Any]], tab_id: int
    ) -> Optional[int]:
        """Resolve user-provided tab_id to an actual tab index.

        Supports both index-style ids (0..N-1) and browser-assigned tab ids.
        """
        if not tabs_info:
            return None

        if 0 <= tab_id < len(tabs_info):
            return tab_id

        for tab in tabs_info:
            if tab.get("id") == tab_id:
                return int(tab["index"])

        return None

    async def _switch_to_tab_index_compatible(
        self, ctx: BrowserContext, tab_index: int
    ) -> None:
        await ctx.switch_to_tab(tab_index)
        page = await ctx.get_current_page()
        await page.wait_for_load_state()

    async def _auto_switch_to_new_tab_if_needed(
        self,
        ctx: BrowserContext,
        before_tabs: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        after_tabs = await self._get_tabs_info(ctx)
        if len(after_tabs) <= len(before_tabs):
            return None

        before_keys = {
            (tab.get("id"), tab.get("url"), tab.get("title")) for tab in before_tabs
        }
        new_tab = None
        for tab in after_tabs:
            key = (tab.get("id"), tab.get("url"), tab.get("title"))
            if key not in before_keys:
                new_tab = tab

        if new_tab is None:
            new_tab = after_tabs[-1]

        await self._switch_to_tab_index_compatible(ctx, int(new_tab["index"]))
        return new_tab

    @staticmethod
    def _split_text_into_chunks(
        text: str, chunk_size: int, overlap: int = 0
    ) -> list[str]:
        """Split long text into overlapping chunks for multi-pass extraction."""
        if not text:
            return []

        if chunk_size <= 0:
            return [text]

        safe_overlap = max(0, min(overlap, chunk_size - 1))
        step = chunk_size - safe_overlap if chunk_size - safe_overlap > 0 else chunk_size

        chunks: list[str] = []
        start = 0
        text_length = len(text)
        while start < text_length:
            end = min(text_length, start + chunk_size)
            chunks.append(text[start:end])
            if end >= text_length:
                break
            start += step

        return chunks

    @staticmethod
    def _build_text_preview(text: str, max_chars: int) -> str:
        """Return a readable preview that preserves both head and tail for long text."""
        if max_chars <= 0 or len(text) <= max_chars:
            return text

        head_chars = max_chars // 2
        tail_chars = max_chars - head_chars
        omitted = len(text) - max_chars
        return (
            f"{text[:head_chars]}\n"
            f"...[{omitted} chars omitted]...\n"
            f"{text[-tail_chars:]}"
        )

    @staticmethod
    def _build_extraction_function_schema() -> dict[str, Any]:
        """Schema used by LLM function calling for chunk-level extraction."""
        return {
            "type": "function",
            "function": {
                "name": "extract_content",
                "description": "Extract specific information from a webpage chunk based on a goal",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "extracted_content": {
                            "type": "object",
                            "description": "Content extracted from the page chunk according to the goal",
                            "properties": {
                                "text": {
                                    "type": "string",
                                    "description": "Text extracted from this chunk",
                                },
                                "metadata": {
                                    "type": "object",
                                    "description": "Optional metadata for the extraction",
                                    "properties": {
                                        "source": {
                                            "type": "string",
                                            "description": "Source URL of the extracted content",
                                        },
                                        "chunk": {
                                            "type": "integer",
                                            "description": "Chunk index (1-based)",
                                        },
                                    },
                                },
                            },
                        }
                    },
                    "required": ["extracted_content"],
                },
            },
        }

    def _get_max_content_length(self) -> int:
        configured = getattr(config.browser_config, "max_content_length", 2000)
        if isinstance(configured, int) and configured > 0:
            return configured
        return 2000

    async def _extract_chunk_with_llm(
        self,
        *,
        goal: str,
        page_url: str,
        chunk_text: str,
        chunk_index: int,
        total_chunks: int,
    ) -> Optional[dict[str, Any]]:
        """Run focused extraction for one chunk and return normalized result."""
        if not self.llm:
            return None

        prompt = f"""\
Your task is to extract information relevant to the goal from this webpage chunk.
If the goal is vague, summarize this chunk.

Goal: {goal}
Source URL: {page_url}
Chunk: {chunk_index}/{total_chunks}

Page chunk content:
{chunk_text}
"""

        response = await self.llm.ask_tool(
            [{"role": "system", "content": prompt}],
            tools=[self._build_extraction_function_schema()],
            tool_choice="required",
        )

        if response and response.tool_calls:
            try:
                arguments = response.tool_calls[0].function.arguments or "{}"
                args = json.loads(arguments)
                extracted_content = args.get("extracted_content")
                if isinstance(extracted_content, dict):
                    return extracted_content
            except Exception:
                # Fall back to plain content handling below.
                pass

        if response and response.content:
            return {
                "text": response.content,
                "metadata": {
                    "source": page_url,
                    "chunk": chunk_index,
                },
            }

        return None

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
                if action == "go_to_url":
                    if not url:
                        return ToolResult(
                            error="URL is required for 'go_to_url' action"
                        )
                    page = await context.get_current_page()
                    await page.goto(url)
                    await page.wait_for_load_state()
                    # Extra wait for dynamic JS-heavy pages (SPA like Bilibili)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass  # networkidle may timeout on pages with persistent connections
                    await asyncio.sleep(1)
                    
                    output = f"Navigated to {url}"
                    return ToolResult(output=output)

                elif action == "go_back":
                    await context.go_back()
                    return ToolResult(output="Navigated back")

                elif action == "refresh":
                    await context.refresh_page()
                    return ToolResult(output="Refreshed current page")

                elif action == "web_search":
                    if not query:
                        return ToolResult(
                            error="Query is required for 'web_search' action"
                        )
                    # Execute the web search and return results directly without browser navigation
                    search_response = await self.web_search_tool.execute(
                        query=query, fetch_content=True, num_results=3
                    )
                    if search_response.error:
                        return ToolResult(error=search_response.error)

                    if not search_response.results:
                        return ToolResult(
                            error="No search results found. Try refining the query."
                        )

                    # Navigate to the first search result
                    first_search_result = next(
                        (result for result in search_response.results if result.url),
                        None,
                    )
                    if not first_search_result:
                        return ToolResult(
                            error="Search results did not include a valid URL to navigate."
                        )

                    url_to_navigate = first_search_result.url

                    page = await context.get_current_page()
                    await page.goto(url_to_navigate)
                    await page.wait_for_load_state()

                    search_response.output = (
                        f"{search_response.output}\n\n"
                        f"Navigated to top result: {url_to_navigate}"
                    )

                    return search_response

                elif action == "inspect_element":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'inspect_element' action"
                        )
                    try:
                        await self._prepare_dom_index_cache(context)
                        element = await context.get_dom_element_by_index(index)
                    except (KeyError, IndexError, Exception) as dom_err:
                        return ToolResult(
                            error=f"Element with index {index} not found in current DOM. "
                                  f"The page may not be fully loaded or the index is invalid. "
                                  f"Try 'wait' then retry. (detail: {type(dom_err).__name__})"
                        )
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")

                    page = await context.get_current_page()
                    element_brief = await self._get_element_brief_by_xpath(
                        page,
                        getattr(element, "xpath", None),
                    )
                    prediction = self._predict_click_effect(page.url, element_brief)

                    payload = {
                        "index": index,
                        "element": element_brief,
                        "predicted_click_effect": prediction,
                    }
                    return ToolResult(
                        output=f"Element inspection:\n{json.dumps(payload, ensure_ascii=False)}"
                    )

                # Element interaction actions
                elif action == "click_element":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'click_element' action"
                        )
                    before_tabs = await self._get_tabs_info(context)
                    before_summary = await self._get_page_summary(context)
                    try:
                        await self._prepare_dom_index_cache(context)
                        element = await context.get_dom_element_by_index(index)
                    except (KeyError, IndexError, Exception) as dom_err:
                        return ToolResult(
                            error=f"Element with index {index} not found in current DOM. "
                                  f"The page may not be fully loaded or the index is invalid. "
                                  f"Try 'extract_content' first to see available elements. (detail: {type(dom_err).__name__})"
                        )
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")

                    page_before_click = await context.get_current_page()
                    element_brief = await self._get_element_brief_by_xpath(
                        page_before_click,
                        getattr(element, "xpath", None),
                    )
                    pre_click_prediction = self._predict_click_effect(
                        str(before_summary.get("url") or ""),
                        element_brief,
                    )

                    download_path = await context._click_element_node(element)
                    try:
                        page_after_click = await context.get_current_page()
                        await page_after_click.wait_for_load_state(
                            "domcontentloaded", timeout=4000
                        )
                    except Exception:
                        pass

                    switched_tab = None
                    try:
                        switched_tab = await self._auto_switch_to_new_tab_if_needed(
                            context, before_tabs
                        )
                    except Exception:
                        switched_tab = None

                    after_summary = await self._get_page_summary(context)
                    feedback = self._build_click_feedback(
                        clicked_by="index",
                        clicked_value=index,
                        element_brief=element_brief,
                        pre_click_prediction=pre_click_prediction,
                        switched_tab=switched_tab,
                        before_summary=before_summary,
                        after_summary=after_summary,
                    )

                    output = f"Clicked element at index {index}"
                    if element_brief:
                        output += (
                            " - Element: "
                            f"tag={element_brief.get('tag') or 'unknown'}, "
                            f"text={element_brief.get('text') or '(empty)'}, "
                            f"href={element_brief.get('href') or '(none)'}"
                        )
                    output += (
                        " - Predicted effect: "
                        f"{json.dumps(pre_click_prediction, ensure_ascii=False)}"
                    )
                    if download_path:
                        output += f" - Downloaded file to {download_path}"
                    if switched_tab:
                        output += (
                            " - Auto-switched to new tab "
                            f"(index={switched_tab.get('index')}, "
                            f"id={switched_tab.get('id')}, "
                            f"title={switched_tab.get('title') or '(untitled)'})"
                        )
                    output += (
                        "\nClick feedback: "
                        f"{json.dumps(feedback, ensure_ascii=False)}"
                    )

                    if feedback.get("outcome") == "likely_misclick":
                        return ToolResult(
                            error=(
                                "Low-confidence click detected. "
                                f"{feedback.get('recommendation')} "
                                f"Feedback={json.dumps(feedback, ensure_ascii=False)}"
                            )
                        )

                    return ToolResult(output=output)

                elif action == "click_text":
                    if not text:
                        return ToolResult(
                            error="Text is required for 'click_text' action"
                        )

                    before_tabs = await self._get_tabs_info(context)
                    before_summary = await self._get_page_summary(context)
                    page = await context.get_current_page()

                    try:
                        exact_locator = page.get_by_text(text, exact=True)
                        await exact_locator.first.click(timeout=2500)
                    except Exception:
                        try:
                            fuzzy_locator = page.get_by_text(text, exact=False)
                            await fuzzy_locator.first.click(timeout=5000)
                        except Exception as click_err:
                            return ToolResult(
                                error=f"Failed to click text '{text}': {click_err}"
                            )

                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

                    switched_tab = None
                    try:
                        switched_tab = await self._auto_switch_to_new_tab_if_needed(
                            context, before_tabs
                        )
                    except Exception:
                        switched_tab = None

                    output = f"Clicked element by text: '{text}'"
                    if switched_tab:
                        output += (
                            " - Auto-switched to new tab "
                            f"(index={switched_tab.get('index')}, "
                            f"id={switched_tab.get('id')}, "
                            f"title={switched_tab.get('title') or '(untitled)'})"
                        )
                    after_summary = await self._get_page_summary(context)
                    feedback = self._build_click_feedback(
                        clicked_by="text",
                        clicked_value=text,
                        element_brief={"tag": "", "text": text, "href": "", "target": ""},
                        pre_click_prediction={
                            "likely_effect": "text_click",
                            "has_link": False,
                            "link_url": "",
                            "same_domain": False,
                            "same_path": False,
                            "opens_new_tab": False,
                            "is_home_navigation": False,
                        },
                        switched_tab=switched_tab,
                        before_summary=before_summary,
                        after_summary=after_summary,
                    )

                    output += (
                        "\nClick feedback: "
                        f"{json.dumps(feedback, ensure_ascii=False)}"
                    )
                    return ToolResult(output=output)

                elif action == "input_text":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"
                        )
                    try:
                        await self._prepare_dom_index_cache(context)
                        element = await context.get_dom_element_by_index(index)
                    except (KeyError, IndexError, Exception) as dom_err:
                        return ToolResult(
                            error=f"Element with index {index} not found in current DOM. "
                                  f"The page may not be fully loaded or the index is invalid. "
                                  f"Try 'extract_content' first to see available elements. (detail: {type(dom_err).__name__})"
                        )
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    await context._input_text_element_node(element, text)
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"
                    )

                elif action == "scroll_down" or action == "scroll_up":
                    direction = 1 if action == "scroll_down" else -1
                    amount = (
                        scroll_amount
                        if scroll_amount is not None
                        else context.config.browser_window_size["height"]
                    )
                    await context.execute_javascript(
                        f"window.scrollBy(0, {direction * amount});"
                    )
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"
                    )

                elif action == "scroll_to_text":
                    if not text:
                        return ToolResult(
                            error="Text is required for 'scroll_to_text' action"
                        )
                    page = await context.get_current_page()
                    try:
                        locator = page.get_by_text(text, exact=False)
                        await locator.scroll_into_view_if_needed()
                        return ToolResult(output=f"Scrolled to text: '{text}'")
                    except Exception as e:
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")

                elif action == "send_keys":
                    if not keys:
                        return ToolResult(
                            error="Keys are required for 'send_keys' action"
                        )
                    page = await context.get_current_page()
                    await page.keyboard.press(keys)
                    return ToolResult(output=f"Sent keys: {keys}")

                elif action == "get_dropdown_options":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'get_dropdown_options' action"
                        )
                    await self._prepare_dom_index_cache(context)
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    options = await page.evaluate(
                        """
                        (xpath) => {
                            const select = document.evaluate(xpath, document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (!select) return null;
                            return Array.from(select.options).map(opt => ({
                                text: opt.text,
                                value: opt.value,
                                index: opt.index
                            }));
                        }
                    """,
                        element.xpath,
                    )
                    return ToolResult(output=f"Dropdown options: {options}")

                elif action == "select_dropdown_option":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'select_dropdown_option' action"
                        )
                    await self._prepare_dom_index_cache(context)
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    await page.select_option(element.xpath, label=text)
                    return ToolResult(
                        output=f"Selected option '{text}' from dropdown at index {index}"
                    )

                # Content extraction actions
                elif action == "extract_content":
                    if not goal:
                        return ToolResult(
                            error="Goal is required for 'extract_content' action"
                        )

                    page = await context.get_current_page()
                    current_url = page.url.lower()
                    import markdownify

                    content = markdownify.markdownify(await page.content()).strip()
                    if not content:
                        return ToolResult(
                            output=(
                                "No content was extracted from the page. "
                                "The page may be empty or still loading. Try 'wait' then retry."
                            )
                        )

                    # Use larger chunk size than state preview so long pages can be covered.
                    chunk_size = max(3000, max_content_length * 2)
                    overlap = min(400, max(100, chunk_size // 10))
                    max_chunks = 8

                    chunks = self._split_text_into_chunks(
                        content,
                        chunk_size=chunk_size,
                        overlap=overlap,
                    )

                    total_chunks = len(chunks)
                    chunks_to_process = chunks[:max_chunks]
                    extraction_results: list[dict[str, Any]] = []

                    for idx, chunk in enumerate(chunks_to_process, start=1):
                        try:
                            extracted = await self._extract_chunk_with_llm(
                                goal=goal,
                                page_url=current_url,
                                chunk_text=chunk,
                                chunk_index=idx,
                                total_chunks=total_chunks,
                            )
                        except Exception as chunk_err:
                            extracted = {
                                "text": f"Chunk extraction failed: {chunk_err}",
                                "metadata": {
                                    "source": current_url,
                                    "chunk": idx,
                                },
                            }

                        if extracted:
                            extraction_results.append(
                                {
                                    "chunk_index": idx,
                                    "chunk_chars": len(chunk),
                                    "extracted_content": extracted,
                                }
                            )

                    if extraction_results:
                        payload = {
                            "goal": goal,
                            "source_url": current_url,
                            "chunks_processed": len(chunks_to_process),
                            "total_chunks": total_chunks,
                            "truncated_chunks": max(0, total_chunks - len(chunks_to_process)),
                            "results": extraction_results,
                        }
                        return ToolResult(
                            output=(
                                "Extracted from page:\n"
                                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
                            )
                        )

                    preview = self._build_text_preview(
                        content,
                        max_chars=max_content_length * 2,
                    )
                    return ToolResult(
                        output=f"Extracted from page (raw preview):\n{preview}\n"
                    )

                # Tab management actions
                elif action == "switch_tab":
                    if tab_id is None:
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"
                        )

                    tabs_info = await self._get_tabs_info(context)
                    resolved_index = self._resolve_tab_switch_index(tabs_info, tab_id)
                    if resolved_index is None:
                        return ToolResult(
                            error=(
                                f"Unable to resolve tab_id={tab_id}. "
                                f"{self._format_tabs_for_output(tabs_info)}"
                            )
                        )

                    await self._switch_to_tab_index_compatible(context, resolved_index)
                    page = await context.get_current_page()
                    output = (
                        f"Switched to tab index={resolved_index} "
                        f"(requested tab_id={tab_id}, current_url={page.url})"
                    )
                    return ToolResult(output=output)

                elif action == "list_tabs":
                    tabs_info = await self._get_tabs_info(context)
                    return ToolResult(output=self._format_tabs_for_output(tabs_info))

                elif action == "open_tab":
                    if not url:
                        return ToolResult(error="URL is required for 'open_tab' action")
                    before_tabs = await self._get_tabs_info(context)
                    await context.create_new_tab(url)
                    switched_tab = None
                    try:
                        switched_tab = await self._auto_switch_to_new_tab_if_needed(
                            context, before_tabs
                        )
                    except Exception:
                        switched_tab = None

                    output = f"Opened new tab with {url}"
                    if switched_tab:
                        output += (
                            " and switched to it "
                            f"(index={switched_tab.get('index')}, id={switched_tab.get('id')})"
                        )
                    return ToolResult(output=output)

                elif action == "close_tab":
                    await context.close_current_tab()
                    return ToolResult(output="Closed current tab")

                # Utility actions
                elif action == "wait":
                    seconds_to_wait = seconds if seconds is not None else 3
                    await asyncio.sleep(seconds_to_wait)
                    return ToolResult(output=f"Waited for {seconds_to_wait} seconds")

                elif action == "get_media_status":
                    page = await context.get_current_page()
                    media_status = await self._get_media_status(page)
                    
                    if not media_status.get('has_video') and not media_status.get('has_audio'):
                        return ToolResult(output="No video or audio elements found on this page.")
                    
                    output_lines = ["📺 Media Status Report:"]
                    if media_status.get('has_video'):
                        is_playing = media_status.get('is_playing', False)
                        duration = media_status.get('duration', 0)
                        current_time = media_status.get('current_time', 0)
                        output_lines.append(f"  - Video: {'▶️ PLAYING' if is_playing else '⏸️ PAUSED/LOADING'}")
                        if duration > 0:
                            output_lines.append(f"  - Progress: {current_time:.1f}s / {duration:.1f}s")
                        output_lines.append(f"  - Muted: {'Yes' if media_status.get('muted') else 'No'}")
                    if media_status.get('has_audio'):
                        output_lines.append(f"  - Audio: Found")
                    
                    if media_status.get('is_playing'):
                        output_lines.append("\n▶️ Media is actively playing.")
                    
                    return ToolResult(output="\n".join(output_lines))

                elif action == "close_browser":
                    self.keep_browser_open = False
                    await self._force_cleanup()
                    return ToolResult(output="Browser has been closed.")

                else:
                    return ToolResult(error=f"Unknown action: {action}")

            except Exception as e:
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")

    async def _get_media_status(self, page) -> dict:
        """Detect video/audio playback status on the current page."""
        try:
            media_info = await page.evaluate("""
                () => {
                    const videos = document.querySelectorAll('video');
                    const audios = document.querySelectorAll('audio');
                    
                    let result = {
                        has_video: videos.length > 0,
                        has_audio: audios.length > 0,
                        is_playing: false,
                        duration: 0,
                        current_time: 0,
                        muted: false
                    };
                    
                    // Check videos
                    for (const video of videos) {
                        if (!video.paused && !video.ended && video.readyState > 2) {
                            result.is_playing = true;
                        }
                        if (video.duration > result.duration) {
                            result.duration = video.duration || 0;
                            result.current_time = video.currentTime || 0;
                            result.muted = video.muted;
                        }
                    }
                    
                    // Check audios if no video playing
                    if (!result.is_playing) {
                        for (const audio of audios) {
                            if (!audio.paused && !audio.ended && audio.readyState > 2) {
                                result.is_playing = true;
                                break;
                            }
                        }
                    }
                    
                    return result;
                }
            """)
            return media_info or {}
        except Exception:
            return {}

    async def get_current_state(
        self, context: Optional[BrowserContext] = None
    ) -> ToolResult:
        """
        Get the current browser state as a ToolResult.
        If context is not provided, uses self.context.
        """
        try:
            # Use provided context or fall back to self.context
            ctx = context or self.context
            if not ctx:
                return ToolResult(error="Browser context not initialized")

            state = await self._get_browser_state_compatible(ctx)

            # Create a viewport_info dictionary if it doesn't exist
            viewport_height = 0
            if hasattr(state, "viewport_info") and state.viewport_info:
                viewport_height = state.viewport_info.height
            elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):
                viewport_height = ctx.config.browser_window_size.get("height", 0)

            # Take a screenshot for the state
            page = await ctx.get_current_page()

            await page.bring_to_front()
            await page.wait_for_load_state()

            screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="jpeg", quality=100
            )

            screenshot = base64.b64encode(screenshot).decode("utf-8")

            # Build the state info with all required fields
            # gather simple page text so the agent can use contextual non-interactive content
            max_content_length = self._get_max_content_length()
            page_text = ""
            page_text_length = 0
            try:
                # innerText gives readable text without HTML markup
                page = await ctx.get_current_page()
                page_text = await page.evaluate("() => document.body.innerText || ''")
                if page_text:
                    page_text_length = len(page_text)
                    if max_content_length:
                        page_text = self._build_text_preview(
                            page_text,
                            max_chars=max_content_length,
                        )
            except Exception:
                # ignore errors retrieving text
                page_text = ""
                page_text_length = 0

            state_info = {
                "url": state.url,
                "title": state.title,
                "tabs": self._normalize_tabs(getattr(state, "tabs", []) or []),
                "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",
                "interactive_elements": (
                    state.element_tree.clickable_elements_to_string()
                    if state.element_tree
                    else ""
                ),
                # include plain text of the page as additional context
                "page_text": page_text,
                "page_text_length": page_text_length,
                "scroll_info": {
                    "pixels_above": getattr(state, "pixels_above", 0),
                    "pixels_below": getattr(state, "pixels_below", 0),
                    "total_height": getattr(state, "pixels_above", 0)
                    + getattr(state, "pixels_below", 0)
                    + viewport_height,
                },
                "viewport_height": viewport_height,
            }

            return ToolResult(
                output=json.dumps(state_info, indent=4, ensure_ascii=False),
                base64_image=screenshot,
            )
        except Exception as e:
            return ToolResult(error=f"Failed to get browser state: {str(e)}")

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
