from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from browser_use.browser.context import BrowserContext


def trim_text(value: Any, max_len: int = 120) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def normalize_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    host = (parsed.netloc or "").lower()
    path = parsed.path or "/"
    normalized_path = path.rstrip("/") or "/"
    return host, normalized_path


def is_home_label(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {
        "home",
        "首页",
        "主页",
        "main",
    }


def has_meaningful_page_change(
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
) -> bool:
    before_host, before_path = normalize_url(str(before_summary.get("url") or ""))
    after_host, after_path = normalize_url(str(after_summary.get("url") or ""))
    if before_host != after_host or before_path != after_path:
        return True

    return int(before_summary.get("tab_count") or 0) != int(
        after_summary.get("tab_count") or 0
    )


def build_click_feedback(
    *,
    clicked_by: str,
    clicked_value: Any,
    element_brief: dict[str, Any],
    pre_click_prediction: Optional[dict[str, Any]],
    switched_tab: Optional[dict[str, Any]],
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
) -> dict[str, Any]:
    before_url = str(before_summary.get("url") or "")
    after_url = str(after_summary.get("url") or "")
    element_text = str(element_brief.get("text") or "")
    element_href = str(element_brief.get("href") or "")

    before_host, before_path = normalize_url(before_url)
    after_host, after_path = normalize_url(after_url)
    href_host, href_path = normalize_url(element_href)

    page_changed = has_meaningful_page_change(before_summary, after_summary)

    is_home_nav = (
        is_home_label(element_text)
        and href_path == "/"
        and bool(href_host)
        and (not before_host or href_host == before_host)
    )

    likely_misclick = bool(is_home_nav and before_path != "/" and after_path == "/")

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
        recommendation = (
            "Outcome is uncertain; verify with list_tabs/extract_content/get_media_status before next step."
        )

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


def predict_click_effect(
    current_url: str,
    element_brief: dict[str, Any],
) -> dict[str, Any]:
    href = str(element_brief.get("href") or "")
    target = str(element_brief.get("target") or "").lower()
    tag = str(element_brief.get("tag") or "").lower()
    text = str(element_brief.get("text") or "")

    current_host, current_path = normalize_url(current_url)
    href_host, href_path = normalize_url(href)

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
        "is_home_navigation": bool(is_home_label(text) and href_path == "/"),
    }


async def get_browser_state_compatible(self, ctx: BrowserContext):
    """Get browser state with compatibility across browser_use versions."""
    try:
        return await ctx.get_state(cache_clickable_elements_hashes=True)
    except TypeError:
        try:
            return await ctx.get_state(True)
        except TypeError:
            return await ctx.get_state()


async def prepare_dom_index_cache(self, ctx: BrowserContext) -> None:
    """Prime browser_use's clickable-element cache before index-based actions."""
    await self._get_browser_state_compatible(ctx)


async def get_page_summary(self, ctx: BrowserContext) -> dict[str, Any]:
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
        "title": trim_text(title, 100),
        "tab_count": len(tabs_info),
    }


async def get_element_brief_by_xpath(
    self,
    page,
    xpath: Optional[str],
) -> dict[str, Any]:
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

    const normalize = (input) => (input || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

    const extractText = (target) => {
        if (!target) {
            return '';
        }

        let extracted = '';
        try {
            if (target.nodeType === Node.ELEMENT_NODE) {
                const clone = target.cloneNode(true);
                if (clone && clone.querySelectorAll) {
                    clone
                        .querySelectorAll('script, style, noscript, template')
                        .forEach((el) => el.remove());
                }
                extracted = normalize((clone && (clone.innerText || clone.textContent)) || '');
            } else {
                extracted = normalize(target.textContent || '');
            }
        } catch (_error) {
            extracted = '';
        }

        if (extracted) {
            return extracted;
        }

        try {
            const textNodes = [];
            const walker = document.createTreeWalker(
                target,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode: (textNode) => {
                        const value = normalize(textNode && textNode.nodeValue);
                        return value ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                    }
                }
            );

            let currentNode = walker.nextNode();
            while (currentNode && textNodes.length < 5000) {
                const value = normalize(currentNode.nodeValue || '');
                if (value) {
                    textNodes.push(value);
                }
                currentNode = walker.nextNode();
            }

            return normalize(textNodes.join(' '));
        } catch (_error) {
            return '';
        }
    };

  const tag = (node.tagName || '').toLowerCase();
    const rawText = extractText(node);
    const text = rawText.slice(0, 120);
    const textPreview = rawText.slice(0, 600);

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
        text_preview: textPreview,
        text_length: rawText.length,
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
                "tag": trim_text(result.get("tag"), 30),
                "text": trim_text(result.get("text"), 120),
                "text_preview": trim_text(result.get("text_preview"), 600),
                "text_length": int(result.get("text_length") or 0),
                "href": trim_text(result.get("href"), 180),
                "target": trim_text(result.get("target"), 20),
                "role": trim_text(result.get("role"), 30),
                "aria_label": trim_text(result.get("aria_label"), 120),
                "class_name": trim_text(result.get("class_name"), 120),
                "id": trim_text(result.get("id"), 60),
                "rect": result.get("rect") if isinstance(result.get("rect"), dict) else {},
            }
    except Exception:
        pass

    return {}


def normalize_tabs(tabs: list[Any]) -> list[dict[str, Any]]:
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


def format_tabs_for_output(tabs_info: list[dict[str, Any]]) -> str:
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


async def get_tabs_info(self, ctx: BrowserContext) -> list[dict[str, Any]]:
    state = await self._get_browser_state_compatible(ctx)
    tabs = getattr(state, "tabs", []) or []
    return self._normalize_tabs(tabs)


def resolve_tab_switch_index(
    tabs_info: list[dict[str, Any]], tab_id: int
) -> Optional[int]:
    """Resolve user-provided tab_id to an actual tab index."""
    if not tabs_info:
        return None

    if 0 <= tab_id < len(tabs_info):
        return tab_id

    for tab in tabs_info:
        if tab.get("id") == tab_id:
            return int(tab["index"])

    return None


async def switch_to_tab_index_compatible(
    self, ctx: BrowserContext, tab_index: int
) -> None:
    await ctx.switch_to_tab(tab_index)
    page = await ctx.get_current_page()
    await page.wait_for_load_state()


async def auto_switch_to_new_tab_if_needed(
    self,
    ctx: BrowserContext,
    before_tabs: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    after_tabs = await self._get_tabs_info(ctx)
    if len(after_tabs) <= len(before_tabs):
        return None

    before_keys = {(tab.get("id"), tab.get("url"), tab.get("title")) for tab in before_tabs}
    new_tab = None
    for tab in after_tabs:
        key = (tab.get("id"), tab.get("url"), tab.get("title"))
        if key not in before_keys:
            new_tab = tab

    if new_tab is None:
        new_tab = after_tabs[-1]

    await self._switch_to_tab_index_compatible(ctx, int(new_tab["index"]))
    return new_tab


def split_text_into_chunks(
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


def build_text_preview(text: str, max_chars: int) -> str:
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
