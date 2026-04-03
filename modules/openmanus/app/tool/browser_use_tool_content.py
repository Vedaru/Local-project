from __future__ import annotations

import base64
import json
from typing import Any, Optional

from browser_use.browser.context import BrowserContext

from app.config import config
from app.tool.base import ToolResult


def build_extraction_function_schema() -> dict[str, Any]:
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


def get_max_content_length(self) -> int:
    configured = getattr(config.browser_config, "max_content_length", 2000)
    if isinstance(configured, int) and configured > 0:
        return configured
    return 2000


async def extract_chunk_with_llm(
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


async def handle_extract_content_action(
    self,
    context: BrowserContext,
    goal: Optional[str],
    max_content_length: int,
) -> ToolResult:
    if not goal:
        return ToolResult(error="Goal is required for 'extract_content' action")

    page = await context.get_current_page()
    current_url = page.url.lower()

    extracted_text, _ = await self._extract_page_text(page)
    content = self._normalize_whitespace_text(extracted_text)
    if len(content) < 400:
        try:
            page_html = await page.content()
        except Exception:
            page_html = ""
        content = self._html_to_text_fallback(page_html)
    if not content:
        return ToolResult(
            output=(
                "No content was extracted from the page. "
                "The page may be empty or still loading. Try 'wait' then retry."
            )
        )

    chunk_size = max(3000, max_content_length * 2)
    overlap = min(400, max(100, chunk_size // 10))
    max_chunks = 8

    chunks = self._split_text_into_chunks(content, chunk_size=chunk_size, overlap=overlap)

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

    preview = self._build_text_preview(content, max_chars=max_content_length * 2)
    return ToolResult(output=f"Extracted from page (raw preview):\n{preview}\n")


async def get_media_status(self, page) -> dict:
    """Detect video/audio playback status on the current page."""
    try:
        media_info = await page.evaluate(
            """
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
            """
        )
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
        ctx = context or self.context
        if not ctx:
            return ToolResult(error="Browser context not initialized")

        state = await self._get_browser_state_compatible(ctx)

        viewport_height = 0
        if hasattr(state, "viewport_info") and state.viewport_info:
            viewport_height = state.viewport_info.height
        elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):
            viewport_height = ctx.config.browser_window_size.get("height", 0)

        page = await ctx.get_current_page()

        await page.bring_to_front()
        await page.wait_for_load_state()

        screenshot = await page.screenshot(full_page=True, animations="disabled", type="jpeg", quality=100)
        screenshot = base64.b64encode(screenshot).decode("utf-8")

        max_content_length = self._get_max_content_length()
        page_text = ""
        page_text_length = 0
        viewport_text = ""
        viewport_text_length = 0
        try:
            page = await ctx.get_current_page()
            viewport_text, viewport_text_length = await self._extract_viewport_text(page)
            page_text, page_text_length = await self._extract_page_text(page)
            if not page_text and viewport_text:
                page_text = viewport_text
                page_text_length = viewport_text_length

            if page_text and max_content_length:
                page_text = self._build_text_preview(page_text, max_chars=max_content_length)

            if viewport_text and max_content_length:
                viewport_preview_limit = max(1200, min(max_content_length, 3000))
                viewport_text = self._build_text_preview(viewport_text, max_chars=viewport_preview_limit)
        except Exception:
            page_text = ""
            page_text_length = 0
            viewport_text = ""
            viewport_text_length = 0

        state_info = {
            "url": state.url,
            "title": state.title,
            "tabs": self._normalize_tabs(getattr(state, "tabs", []) or []),
            "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",
            "page_text": page_text,
            "page_text_length": page_text_length,
            "viewport_text": viewport_text,
            "viewport_text_length": viewport_text_length,
            "interactive_elements": (
                state.element_tree.clickable_elements_to_string() if state.element_tree else ""
            ),
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
