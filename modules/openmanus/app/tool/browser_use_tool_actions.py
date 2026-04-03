from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from browser_use.browser.context import BrowserContext

from app.tool.base import ToolResult


async def handle_click_element_action(
    self,
    context: BrowserContext,
    index: Optional[int],
) -> ToolResult:
    if index is None:
        return ToolResult(error="Index is required for 'click_element' action")

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
        await page_after_click.wait_for_load_state("domcontentloaded", timeout=4000)
    except Exception:
        pass

    switched_tab = None
    try:
        switched_tab = await self._auto_switch_to_new_tab_if_needed(context, before_tabs)
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
    output += " - Predicted effect: " f"{json.dumps(pre_click_prediction, ensure_ascii=False)}"
    if download_path:
        output += f" - Downloaded file to {download_path}"
    if switched_tab:
        output += (
            " - Auto-switched to new tab "
            f"(index={switched_tab.get('index')}, "
            f"id={switched_tab.get('id')}, "
            f"title={switched_tab.get('title') or '(untitled)'})"
        )
    output += "\nClick feedback: " f"{json.dumps(feedback, ensure_ascii=False)}"

    if feedback.get("outcome") == "likely_misclick":
        return ToolResult(
            error=(
                "Low-confidence click detected. "
                f"{feedback.get('recommendation')} "
                f"Feedback={json.dumps(feedback, ensure_ascii=False)}"
            )
        )

    return ToolResult(output=output)


async def handle_click_text_action(
    self,
    context: BrowserContext,
    text: Optional[str],
) -> ToolResult:
    if not text:
        return ToolResult(error="Text is required for 'click_text' action")

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
            return ToolResult(error=f"Failed to click text '{text}': {click_err}")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass

    switched_tab = None
    try:
        switched_tab = await self._auto_switch_to_new_tab_if_needed(context, before_tabs)
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

    output += "\nClick feedback: " f"{json.dumps(feedback, ensure_ascii=False)}"
    return ToolResult(output=output)


async def handle_interaction_action(
    self,
    context: BrowserContext,
    action: str,
    index: Optional[int],
    text: Optional[str],
    scroll_amount: Optional[int],
    keys: Optional[str],
) -> Optional[ToolResult]:
    if action == "input_text":
        if index is None or not text:
            return ToolResult(error="Index and text are required for 'input_text' action")
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
        return ToolResult(output=f"Input '{text}' into element at index {index}")

    if action == "scroll_down" or action == "scroll_up":
        direction = 1 if action == "scroll_down" else -1
        amount = scroll_amount if scroll_amount is not None else context.config.browser_window_size["height"]
        await context.execute_javascript(f"window.scrollBy(0, {direction * amount});")
        return ToolResult(output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels")

    if action == "scroll_to_text":
        if not text:
            return ToolResult(error="Text is required for 'scroll_to_text' action")
        page = await context.get_current_page()
        try:
            locator = page.get_by_text(text, exact=False)
            await locator.scroll_into_view_if_needed()
            return ToolResult(output=f"Scrolled to text: '{text}'")
        except Exception as e:
            return ToolResult(error=f"Failed to scroll to text: {str(e)}")

    if action == "send_keys":
        if not keys:
            return ToolResult(error="Keys are required for 'send_keys' action")
        page = await context.get_current_page()
        await page.keyboard.press(keys)
        return ToolResult(output=f"Sent keys: {keys}")

    if action == "get_dropdown_options":
        if index is None:
            return ToolResult(error="Index is required for 'get_dropdown_options' action")
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

    if action == "select_dropdown_option":
        if index is None or not text:
            return ToolResult(error="Index and text are required for 'select_dropdown_option' action")
        await self._prepare_dom_index_cache(context)
        element = await context.get_dom_element_by_index(index)
        if not element:
            return ToolResult(error=f"Element with index {index} not found")
        page = await context.get_current_page()
        await page.select_option(element.xpath, label=text)
        return ToolResult(output=f"Selected option '{text}' from dropdown at index {index}")

    return None


async def handle_navigation_action(
    self,
    context: BrowserContext,
    action: str,
    url: Optional[str],
    query: Optional[str],
    index: Optional[int],
) -> Optional[ToolResult]:
    if action == "go_to_url":
        if not url:
            return ToolResult(error="URL is required for 'go_to_url' action")
        page = await context.get_current_page()
        await page.goto(url)
        await page.wait_for_load_state()
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(1)
        return ToolResult(output=f"Navigated to {url}")

    if action == "go_back":
        await context.go_back()
        return ToolResult(output="Navigated back")

    if action == "refresh":
        await context.refresh_page()
        return ToolResult(output="Refreshed current page")

    if action == "web_search":
        if not query:
            return ToolResult(error="Query is required for 'web_search' action")
        search_response = await self.web_search_tool.execute(query=query, fetch_content=True, num_results=3)
        if search_response.error:
            return ToolResult(error=search_response.error)

        if not search_response.results:
            return ToolResult(error="No search results found. Try refining the query.")

        first_search_result = next((result for result in search_response.results if result.url), None)
        if not first_search_result:
            return ToolResult(error="Search results did not include a valid URL to navigate.")

        url_to_navigate = first_search_result.url

        page = await context.get_current_page()
        await page.goto(url_to_navigate)
        await page.wait_for_load_state()

        search_response.output = (
            f"{search_response.output}\n\n"
            f"Navigated to top result: {url_to_navigate}"
        )

        return search_response

    if action == "inspect_element":
        if index is None:
            return ToolResult(error="Index is required for 'inspect_element' action")
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
        element_brief = await self._get_element_brief_by_xpath(page, getattr(element, "xpath", None))
        prediction = self._predict_click_effect(page.url, element_brief)

        payload = {
            "index": index,
            "element": element_brief,
            "predicted_click_effect": prediction,
        }
        return ToolResult(output=f"Element inspection:\n{json.dumps(payload, ensure_ascii=False)}")

    return None


async def handle_tab_action(
    self,
    context: BrowserContext,
    action: str,
    tab_id: Optional[int],
    url: Optional[str],
) -> Optional[ToolResult]:
    if action == "switch_tab":
        if tab_id is None:
            return ToolResult(error="Tab ID is required for 'switch_tab' action")

        tabs_info = await self._get_tabs_info(context)
        resolved_index = self._resolve_tab_switch_index(tabs_info, tab_id)
        if resolved_index is None:
            return ToolResult(error=(f"Unable to resolve tab_id={tab_id}. " f"{self._format_tabs_for_output(tabs_info)}"))

        await self._switch_to_tab_index_compatible(context, resolved_index)
        page = await context.get_current_page()
        output = f"Switched to tab index={resolved_index} " f"(requested tab_id={tab_id}, current_url={page.url})"
        return ToolResult(output=output)

    if action == "list_tabs":
        tabs_info = await self._get_tabs_info(context)
        return ToolResult(output=self._format_tabs_for_output(tabs_info))

    if action == "open_tab":
        if not url:
            return ToolResult(error="URL is required for 'open_tab' action")
        before_tabs = await self._get_tabs_info(context)
        await context.create_new_tab(url)
        switched_tab = None
        try:
            switched_tab = await self._auto_switch_to_new_tab_if_needed(context, before_tabs)
        except Exception:
            switched_tab = None

        output = f"Opened new tab with {url}"
        if switched_tab:
            output += " and switched to it " f"(index={switched_tab.get('index')}, id={switched_tab.get('id')})"
        return ToolResult(output=output)

    if action == "close_tab":
        await context.close_current_tab()
        return ToolResult(output="Closed current tab")

    return None


async def handle_utility_action(
    self,
    context: BrowserContext,
    action: str,
    seconds: Optional[int],
) -> Optional[ToolResult]:
    if action == "wait":
        seconds_to_wait = seconds if seconds is not None else 3
        await asyncio.sleep(seconds_to_wait)
        return ToolResult(output=f"Waited for {seconds_to_wait} seconds")

    if action == "get_media_status":
        page = await context.get_current_page()
        media_status = await self._get_media_status(page)

        if not media_status.get("has_video") and not media_status.get("has_audio"):
            return ToolResult(output="No video or audio elements found on this page.")

        output_lines = ["📺 Media Status Report:"]
        if media_status.get("has_video"):
            is_playing = media_status.get("is_playing", False)
            duration = media_status.get("duration", 0)
            current_time = media_status.get("current_time", 0)
            output_lines.append(f"  - Video: {'▶️ PLAYING' if is_playing else '⏸️ PAUSED/LOADING'}")
            if duration > 0:
                output_lines.append(f"  - Progress: {current_time:.1f}s / {duration:.1f}s")
            output_lines.append(f"  - Muted: {'Yes' if media_status.get('muted') else 'No'}")
        if media_status.get("has_audio"):
            output_lines.append("  - Audio: Found")

        if media_status.get("is_playing"):
            output_lines.append("\n▶️ Media is actively playing.")

        return ToolResult(output="\n".join(output_lines))

    if action == "close_browser":
        self.keep_browser_open = False
        await self._force_cleanup()
        return ToolResult(output="Browser has been closed.")

    return None
