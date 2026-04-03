from __future__ import annotations

import re
from typing import Any

_PAGE_TEXT_EXTRACTION_SCRIPT = """
() => {
  const normalize = (input) => (input || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

  const textFromNode = (node) => {
    if (!node) {
      return '';
    }

    const clone = node.cloneNode(true);
    const removeSelectors = [
      'script',
      'style',
      'noscript',
      'template',
      'svg',
      'canvas',
      'form',
      'button',
      'input',
      'select',
      'textarea',
      'nav',
      'header',
      'footer',
      'aside'
    ];

    clone.querySelectorAll(removeSelectors.join(',')).forEach((el) => el.remove());
    return normalize(clone.innerText || clone.textContent || '');
  };

  const candidateSelectors = [
    'article',
    'main article',
    '[role="main"] article',
    'main',
    '[role="main"]',
    '.article-content',
    '.post-content',
    '.entry-content',
    '.markdown-body',
    '#article-content',
    '#content',
    '.content'
  ];

  let mainText = '';
  for (const selector of candidateSelectors) {
    const nodes = document.querySelectorAll(selector);
    nodes.forEach((node) => {
      const candidate = textFromNode(node);
      if (candidate.length > mainText.length) {
        mainText = candidate;
      }
    });
  }

  const bodyText = textFromNode(document.body);
  return {
    mainText,
    bodyText
  };
}
"""

_VIEWPORT_TEXT_EXTRACTION_SCRIPT = """
() => {
  const normalize = (input) => (input || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

  const isNodeVisible = (node) => {
    if (!node) {
      return false;
    }

    const style = window.getComputedStyle(node);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
      return false;
    }

    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return false;
    }

    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    return rect.bottom > 0 && rect.top < viewportHeight;
  };

  const selectors = [
    'article p',
    'main p',
    'p',
    'li',
    'dt',
    'dd',
    'blockquote',
    'pre',
    'code',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6'
  ];

  const visibleTextBlocks = [];
  const seen = new Set();
  document.querySelectorAll(selectors.join(',')).forEach((node) => {
    if (!isNodeVisible(node)) {
      return;
    }

    const text = normalize(node.innerText || node.textContent || '');
    if (!text || text.length < 2 || seen.has(text)) {
      return;
    }

    seen.add(text);
    visibleTextBlocks.push(text);
  });

  if (!visibleTextBlocks.length && document.body && isNodeVisible(document.body)) {
    const bodyText = normalize(document.body.innerText || document.body.textContent || '');
    if (bodyText) {
      visibleTextBlocks.push(bodyText);
    }
  }

  return visibleTextBlocks.join('\n');
}
"""


def normalize_whitespace_text(value: Any) -> str:
    """Normalize extracted text for stable prompt and chunking behavior."""
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split())


def html_to_text_fallback(html: str) -> str:
    """Best-effort HTML to text conversion without requiring optional packages."""
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg", "canvas"]):
            tag.decompose()
        bs_text = normalize_whitespace_text(soup.get_text(" ", strip=True))
        if bs_text:
            return bs_text
    except Exception:
        pass

    try:
        import html2text

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        plain_text = converter.handle(html)
        normalized_plain = normalize_whitespace_text(plain_text)
        if normalized_plain:
            return normalized_plain
    except Exception:
        pass

    try:
        stripped = re.sub(r"<[^>]+>", " ", html)
        normalized_stripped = normalize_whitespace_text(stripped)
        if normalized_stripped:
            return normalized_stripped
    except Exception:
        pass

    return ""


async def extract_markdown_text(page) -> tuple[str, int]:
    """Fallback extraction from raw HTML when DOM text extraction is unstable."""
    try:
        html = await page.content()
    except Exception:
        return "", 0

    normalized_html_text = html_to_text_fallback(html or "")
    if normalized_html_text:
        return normalized_html_text, len(normalized_html_text)

    try:
        import markdownify

        markdown_text = markdownify.markdownify(html or "").strip()
        normalized = normalize_whitespace_text(markdown_text)
        return normalized, len(normalized)
    except Exception:
        return "", 0


def select_preferred_page_text(main_text: str, body_text: str) -> str:
    """Prefer main/article text when it looks substantial enough."""
    normalized_main = normalize_whitespace_text(main_text)
    normalized_body = normalize_whitespace_text(body_text)

    if not normalized_main:
        return normalized_body
    if not normalized_body:
        return normalized_main

    min_main_len = max(240, int(len(normalized_body) * 0.2))
    if len(normalized_main) >= min_main_len:
        return normalized_main
    return normalized_body


async def extract_page_text(page) -> tuple[str, int]:
    """Extract readable page text, prioritizing article-like containers."""
    try:
        extracted = await page.evaluate(_PAGE_TEXT_EXTRACTION_SCRIPT)
        if isinstance(extracted, dict):
            preferred_text = select_preferred_page_text(
                str(extracted.get("mainText") or ""),
                str(extracted.get("bodyText") or ""),
            )
            if preferred_text:
                return preferred_text, len(preferred_text)
    except Exception:
        pass

    try:
        fallback_text = await page.evaluate(
            "() => (document.body && (document.body.innerText || document.body.textContent)) || ''"
        )
        normalized_fallback = normalize_whitespace_text(fallback_text)
        if normalized_fallback:
            return normalized_fallback, len(normalized_fallback)
    except Exception:
        pass

    return await extract_markdown_text(page)


async def extract_viewport_text(page) -> tuple[str, int]:
    """Extract text currently visible in viewport so agents can read on-screen paragraphs."""
    try:
        visible_text = await page.evaluate(_VIEWPORT_TEXT_EXTRACTION_SCRIPT)
        normalized_visible_text = normalize_whitespace_text(visible_text)
        if normalized_visible_text:
            return normalized_visible_text, len(normalized_visible_text)
    except Exception:
        pass

    return "", 0
