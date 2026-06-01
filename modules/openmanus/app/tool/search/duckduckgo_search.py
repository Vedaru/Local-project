from typing import Any, Iterable, List

# duckduckgo_search 已更名为 ddgs，优先使用新包
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from app.tool.search.base import SearchItem, WebSearchEngine

# 后端优先级：html/lite 从 DuckDuckGo 官方端点获取，比 bing 后端更稳定
_BACKEND_FALLBACK_ORDER = ("html", "lite", "auto")


def _ddgs_text_search(query: str, num_results: int) -> Iterable[Any]:
    """按后端优先级依次尝试搜索，兼容 duckduckgo_search 8.x。"""
    ddgs = DDGS()
    last_error: Exception | None = None
    for backend in _BACKEND_FALLBACK_ORDER:
        try:
            return ddgs.text(query, max_results=num_results, backend=backend)
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return []


class DuckDuckGoSearchEngine(WebSearchEngine):
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        DuckDuckGo search engine.

        Returns results formatted according to SearchItem model.
        """
        raw_results = _ddgs_text_search(query, num_results)

        results = []
        for i, item in enumerate(raw_results or []):
            if isinstance(item, str):
                # If it's just a URL
                results.append(
                    SearchItem(
                        title=f"DuckDuckGo Result {i + 1}", url=item, description=None
                    )
                )
            elif isinstance(item, dict):
                # Extract data from the dictionary
                results.append(
                    SearchItem(
                        title=item.get("title", f"DuckDuckGo Result {i + 1}"),
                        url=item.get("href", ""),
                        description=item.get("body", None),
                    )
                )
            else:
                # Try to extract attributes directly
                try:
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"DuckDuckGo Result {i + 1}"),
                            url=getattr(item, "href", ""),
                            description=getattr(item, "body", None),
                        )
                    )
                except Exception:
                    # Fallback
                    results.append(
                        SearchItem(
                            title=f"DuckDuckGo Result {i + 1}",
                            url=str(item),
                            description=None,
                        )
                    )

        return results
