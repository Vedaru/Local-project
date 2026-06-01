from app.tool.search.base import WebSearchEngine

try:
    from app.tool.search.bing_search import BingSearchEngine
except ImportError:
    BingSearchEngine = None  # type: ignore[misc, assignment]

try:
    from app.tool.search.duckduckgo_search import DuckDuckGoSearchEngine
except ImportError:
    DuckDuckGoSearchEngine = None  # type: ignore[misc, assignment]

try:
    from app.tool.search.baidu_search import BaiduSearchEngine
except ImportError:
    BaiduSearchEngine = None  # type: ignore[misc, assignment]

try:
    from app.tool.search.google_search import GoogleSearchEngine
except ImportError:
    GoogleSearchEngine = None  # type: ignore[misc, assignment]

__all__ = [
    "WebSearchEngine",
    "BaiduSearchEngine",
    "DuckDuckGoSearchEngine",
    "GoogleSearchEngine",
    "BingSearchEngine",
]
