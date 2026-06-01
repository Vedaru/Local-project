import asyncio
import importlib
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.browser_text_extractor import normalize_whitespace_text
from app.tool.search import (
    BaiduSearchEngine,
    BingSearchEngine,
    DuckDuckGoSearchEngine,
    GoogleSearchEngine,
    WebSearchEngine,
)
from app.tool.search.base import SearchItem


def _build_search_engine_map() -> Dict[str, WebSearchEngine]:
    """仅注册当前环境已安装依赖的搜索引擎。"""
    engines: Dict[str, WebSearchEngine] = {}

    def _try_add(name: str, factory) -> None:
        try:
            engines[name] = factory()
        except ImportError as exc:
            logger.warning("搜索引擎 %s 不可用（缺少依赖）: %s", name, exc)
        except Exception as exc:
            logger.warning("搜索引擎 %s 初始化失败: %s", name, exc)

    for name, cls in (
        ("duckduckgo", DuckDuckGoSearchEngine),
        ("bing", BingSearchEngine),
        ("google", GoogleSearchEngine),
        ("baidu", BaiduSearchEngine),
    ):
        if cls is not None:
            _try_add(name, cls)

    if not engines:
        logger.error("没有可用的搜索引擎，请安装 duckduckgo_search 或 baidusearch")
    return engines


_SEARCH_ENGINE_CACHE: Optional[Dict[str, WebSearchEngine]] = None


class SearchResult(BaseModel):
    """Represents a single search result returned by a search engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    position: int = Field(description="Position in search results")
    url: str = Field(description="URL of the search result")
    title: str = Field(default="", description="Title of the search result")
    description: str = Field(
        default="", description="Description or snippet of the search result"
    )
    source: str = Field(description="The search engine that provided this result")
    raw_content: Optional[str] = Field(
        default=None, description="Raw content from the search result page if available"
    )

    def __str__(self) -> str:
        """String representation of a search result."""
        return f"{self.title} ({self.url})"


class SearchMetadata(BaseModel):
    """Metadata about the search operation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_results: int = Field(description="Total number of results found")
    language: str = Field(description="Language code used for the search")
    country: str = Field(description="Country code used for the search")


class SearchResponse(ToolResult):
    """Structured response from the web search tool, inheriting ToolResult."""

    query: str = Field(description="The search query that was executed")
    results: List[SearchResult] = Field(
        default_factory=list, description="List of search results"
    )
    metadata: Optional[SearchMetadata] = Field(
        default=None, description="Metadata about the search"
    )

    @model_validator(mode="after")
    def populate_output(self) -> "SearchResponse":
        """Populate output or error fields based on search results."""
        if self.error:
            return self

        result_text = [f"Search results for '{self.query}':"]

        for i, result in enumerate(self.results, 1):
            # Add title with position number
            title = result.title.strip() or "No title"
            result_text.append(f"\n{i}. {title}")

            # Add URL with proper indentation
            result_text.append(f"   URL: {result.url}")

            # Add description if available
            if result.description.strip():
                result_text.append(f"   Description: {result.description}")

            # Add content preview if available
            if result.raw_content:
                content_preview = result.raw_content[:1000].replace("\n", " ").strip()
                if len(result.raw_content) > 1000:
                    content_preview += "..."
                result_text.append(f"   Content: {content_preview}")

        # Add metadata at the bottom if available
        if self.metadata:
            result_text.extend(
                [
                    f"\nMetadata:",
                    f"- Total results: {self.metadata.total_results}",
                    f"- Language: {self.metadata.language}",
                    f"- Country: {self.metadata.country}",
                ]
            )

        self.output = "\n".join(result_text)
        return self


class WebContentFetcher:
    """Utility class for fetching web content."""

    MAX_CONTENT_CHARS = 10000
    MIN_VALID_CONTENT_CHARS = 220
    RUST_FETCHER_EXT_ENV = "WEB_FETCHER_RS_PY_EXT"
    RUST_FETCHER_EXT_MODULE = "_web_fetcher_rs"
    RUST_FETCHER_EXT_RELATIVE_PATHS = (
        ("rust_modules", "web_fetcher_rs", "target", "release"),
        ("rust_modules", "web_fetcher_rs", "target", "debug"),
    )
    _rust_fetcher_module_cache: Optional[Any] = None
    _rust_fetcher_module_attempted: bool = False
    _rust_fetcher_extension_missing_logged: bool = False
    _rust_fetcher_windows_dll_handles: List[Any] = []
    _rust_fetcher_windows_dll_dirs_seen: set[str] = set()
    _rust_fetcher_stats: Dict[str, int] = {
        "requests": 0,
        "extension_attempts": 0,
        "extension_success": 0,
        "extension_empty_or_error": 0,
        "extension_unusable": 0,
        "extension_unavailable": 0,
    }
    BLOCKED_PAGE_HINTS = (
        "captcha",
        "access denied",
        "forbidden",
        "security check",
        "verify",
        "are you human",
        "enable javascript",
        "request blocked",
        "temporarily unavailable",
        "限制本次访问",
        "知乎小管家",
        "请求参数异常",
        "升级客户端后重试",
        '"code":40362',
        '"code":10003',
    )

    @classmethod
    def _increment_rust_fetcher_stat(cls, key: str) -> None:
        cls._rust_fetcher_stats[key] = int(cls._rust_fetcher_stats.get(key, 0)) + 1

    @classmethod
    def _increment_rust_fetcher_stat_by(cls, key: str, amount: int) -> None:
        if amount <= 0:
            return
        cls._rust_fetcher_stats[key] = int(cls._rust_fetcher_stats.get(key, 0)) + amount

    @classmethod
    def reset_rust_fetcher_stats(cls) -> None:
        for key in cls._rust_fetcher_stats:
            cls._rust_fetcher_stats[key] = 0

    @classmethod
    def get_rust_fetcher_stats(cls) -> Dict[str, Any]:
        return dict(cls._rust_fetcher_stats)

    @classmethod
    def _trim_output(cls, text: str) -> str:
        normalized = normalize_whitespace_text(text)
        return normalized[: cls.MAX_CONTENT_CHARS] if normalized else ""

    @classmethod
    def _project_root(cls) -> Path:
        return Path(__file__).resolve().parents[4]

    @classmethod
    def _candidate_extension_paths(cls) -> List[Path]:
        candidates: List[Path] = []
        seen: set[str] = set()

        def _append_candidate(candidate_path: Path) -> None:
            try:
                resolved = candidate_path.expanduser().resolve()
            except Exception:
                return

            if not resolved.exists() or not resolved.is_file():
                return

            key = str(resolved)
            if key in seen:
                return

            seen.add(key)
            candidates.append(resolved)

        def _append_from_directory(directory: Path) -> None:
            if not directory.exists() or not directory.is_dir():
                return

            for suffix in importlib.machinery.EXTENSION_SUFFIXES:
                _append_candidate(directory / f"{cls.RUST_FETCHER_EXT_MODULE}{suffix}")

            for pattern in (
                f"{cls.RUST_FETCHER_EXT_MODULE}*.pyd",
                f"{cls.RUST_FETCHER_EXT_MODULE}*.so",
                f"{cls.RUST_FETCHER_EXT_MODULE}*.dll",
                f"{cls.RUST_FETCHER_EXT_MODULE}*.dylib",
            ):
                for path in sorted(directory.glob(pattern)):
                    _append_candidate(path)

        env_path = os.environ.get(cls.RUST_FETCHER_EXT_ENV)
        if env_path:
            env_candidate = Path(env_path).expanduser()
            if env_candidate.is_dir():
                _append_from_directory(env_candidate)
            else:
                _append_candidate(env_candidate)

        project_root = cls._project_root()
        for relative_path in cls.RUST_FETCHER_EXT_RELATIVE_PATHS:
            _append_from_directory(project_root.joinpath(*relative_path))

        return candidates

    @classmethod
    def _register_windows_dll_dirs(cls, extra_dirs: Optional[List[Path]] = None) -> None:
        if os.name != "nt":
            return

        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is None:
            return

        candidate_dirs: List[Path] = []
        if extra_dirs:
            candidate_dirs.extend(extra_dirs)

        path_raw = os.environ.get("PATH", "")
        if path_raw:
            for item in path_raw.split(os.pathsep):
                item = item.strip().strip('"')
                if item:
                    candidate_dirs.append(Path(item))

        rustup_home = os.environ.get(
            "RUSTUP_HOME",
            str(Path.home() / ".rustup"),
        )
        candidate_dirs.extend(
            [
                Path("D:/mingw64/bin"),
                Path("C:/mingw64/bin"),
                Path(rustup_home) / "toolchains" / "stable-x86_64-pc-windows-gnu" / "bin",
                Path(rustup_home) / "toolchains" / "stable-x86_64-pc-windows-msvc" / "bin",
                Path.home()
                / "AppData"
                / "Local"
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "MartinStorsjo.LLVM-MinGW.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe"
                / "llvm-mingw-20260324-ucrt-x86_64"
                / "bin",
            ]
        )

        for candidate_dir in candidate_dirs:
            try:
                resolved = str(candidate_dir.resolve())
            except Exception:
                resolved = str(candidate_dir)

            normalized = resolved.lower().rstrip("\\/")
            if not normalized or normalized in cls._rust_fetcher_windows_dll_dirs_seen:
                continue

            if not Path(resolved).exists():
                continue

            try:
                handle = add_dll_directory(resolved)
                cls._rust_fetcher_windows_dll_handles.append(handle)
                cls._rust_fetcher_windows_dll_dirs_seen.add(normalized)
            except Exception:
                continue

    @classmethod
    def _load_extension_module_from_path(cls, extension_path: Path) -> Optional[Any]:
        cls._register_windows_dll_dirs([extension_path.parent])

        module_name = cls.RUST_FETCHER_EXT_MODULE
        loader = importlib.machinery.ExtensionFileLoader(module_name, str(extension_path))
        spec = importlib.util.spec_from_file_location(
            module_name,
            str(extension_path),
            loader=loader,
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        if not hasattr(module, "fetch_content"):
            sys.modules.pop(module_name, None)
            return None

        return module

    @classmethod
    def _load_rust_fetcher_module(cls) -> Optional[Any]:
        if cls._rust_fetcher_module_cache is not None:
            return cls._rust_fetcher_module_cache

        if cls._rust_fetcher_module_attempted:
            return None

        cls._rust_fetcher_module_attempted = True

        extension_paths = cls._candidate_extension_paths()
        cls._register_windows_dll_dirs([path.parent for path in extension_paths])

        try:
            module = importlib.import_module(cls.RUST_FETCHER_EXT_MODULE)
            if hasattr(module, "fetch_content"):
                cls._rust_fetcher_module_cache = module
                return module
        except Exception as exc:
            logger.debug(f"Rust extension import by module name failed: {exc}")

        for extension_path in extension_paths:
            try:
                module = cls._load_extension_module_from_path(extension_path)
                if module is not None:
                    cls._rust_fetcher_module_cache = module
                    return module
            except Exception as exc:
                logger.debug(
                    f"Rust extension import failed from {extension_path}: {exc}"
                )

        return None

    @classmethod
    def _run_rust_extension_sync(cls, rust_module: Any, url: str, timeout: int) -> str:
        try:
            payload = rust_module.fetch_content(url, timeout, cls.MAX_CONTENT_CHARS)
        except Exception as exc:
            logger.warning(f"Rust extension fetch failed for {url}: {exc}")
            return ""

        if not isinstance(payload, (tuple, list)) or len(payload) != 3:
            logger.warning(f"Rust extension returned unexpected payload for {url}")
            return ""

        success, content, error = payload
        if bool(success) and isinstance(content, str):
            return cls._trim_output(content)

        error_message = normalize_whitespace_text(str(error or ""))[:300]
        if error_message:
            logger.warning(
                f"Rust extension reported no usable content for {url}: {error_message}"
            )

        if isinstance(content, str):
            return cls._trim_output(content)
        return ""

    @classmethod
    def _run_rust_extension_batch_sync(
        cls,
        rust_module: Any,
        urls: List[str],
        timeout: int,
    ) -> Dict[str, str]:
        if not hasattr(rust_module, "fetch_content_batch"):
            return {}

        try:
            payload = rust_module.fetch_content_batch(
                urls,
                timeout,
                cls.MAX_CONTENT_CHARS,
            )
        except Exception as exc:
            logger.warning(f"Rust extension batch fetch failed: {exc}")
            return {}

        if not isinstance(payload, (list, tuple)):
            logger.warning("Rust extension batch fetch returned unexpected payload")
            return {}

        if len(payload) != len(urls):
            logger.warning(
                "Rust extension batch fetch returned mismatched result count: "
                f"expected={len(urls)} actual={len(payload)}"
            )

        content_by_url: Dict[str, str] = {}
        for index, url in enumerate(urls):
            item = payload[index] if index < len(payload) else None
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                cls._increment_rust_fetcher_stat("extension_empty_or_error")
                continue

            success, content, error = item
            trimmed_content = cls._trim_output(content) if isinstance(content, str) else ""

            if cls._is_usable_content(trimmed_content):
                content_by_url[url] = trimmed_content
                cls._increment_rust_fetcher_stat("extension_success")
                continue

            if trimmed_content:
                cls._increment_rust_fetcher_stat("extension_unusable")
            else:
                cls._increment_rust_fetcher_stat("extension_empty_or_error")

            error_message = normalize_whitespace_text(str(error or ""))[:300]
            if error_message:
                logger.warning(
                    "Rust extension reported no usable content "
                    f"for {url}: {error_message}"
                )

            if bool(success) and isinstance(content, str):
                fallback_content = cls._trim_output(content)
                if cls._is_usable_content(fallback_content):
                    content_by_url[url] = fallback_content
                    cls._increment_rust_fetcher_stat("extension_success")

        return content_by_url

    @classmethod
    async def _fetch_many_with_rust(cls, urls: List[str], timeout: int) -> Dict[str, str]:
        if not urls:
            return {}

        cls._increment_rust_fetcher_stat_by("requests", len(urls))
        rust_module = cls._load_rust_fetcher_module()
        if rust_module is None:
            if not cls._rust_fetcher_extension_missing_logged:
                logger.warning(
                    "Rust web fetcher extension is unavailable. "
                    "Build/install rust_modules/web_fetcher_rs or set WEB_FETCHER_RS_PY_EXT."
                )
                cls._rust_fetcher_extension_missing_logged = True
            cls._increment_rust_fetcher_stat_by("extension_unavailable", len(urls))
            return {}

        loop = asyncio.get_running_loop()
        cls._increment_rust_fetcher_stat_by("extension_attempts", len(urls))

        if hasattr(rust_module, "fetch_content_batch"):
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: cls._run_rust_extension_batch_sync(
                        rust_module,
                        urls,
                        timeout,
                    ),
                )
            except Exception as exc:
                logger.warning(f"Rust extension batch execution failed: {exc}")
                cls._increment_rust_fetcher_stat_by(
                    "extension_empty_or_error", len(urls)
                )
                return {}

        tasks = [
            loop.run_in_executor(
                None,
                lambda target_url=url: cls._run_rust_extension_sync(
                    rust_module,
                    target_url,
                    timeout,
                ),
            )
            for url in urls
        ]
        payloads = await asyncio.gather(*tasks, return_exceptions=True)
        content_by_url: Dict[str, str] = {}
        for url, payload in zip(urls, payloads):
            if isinstance(payload, Exception):
                logger.warning(
                    f"Rust extension fetch failed for {url} with exception: {payload}"
                )
                cls._increment_rust_fetcher_stat("extension_empty_or_error")
                continue

            if cls._is_usable_content(payload):
                content_by_url[url] = payload
                cls._increment_rust_fetcher_stat("extension_success")
            elif payload:
                cls._increment_rust_fetcher_stat("extension_unusable")
            else:
                cls._increment_rust_fetcher_stat("extension_empty_or_error")

        return content_by_url

    @classmethod
    async def _fetch_with_rust(cls, url: str, timeout: int) -> str:
        cls._increment_rust_fetcher_stat("requests")

        rust_module = cls._load_rust_fetcher_module()
        extension_content = ""
        if rust_module is not None:
            try:
                cls._increment_rust_fetcher_stat("extension_attempts")
                loop = asyncio.get_running_loop()
                extension_content = await loop.run_in_executor(
                    None,
                    lambda: cls._run_rust_extension_sync(rust_module, url, timeout),
                )
                if extension_content:
                    if cls._is_usable_content(extension_content):
                        cls._increment_rust_fetcher_stat("extension_success")
                        return extension_content
                    cls._increment_rust_fetcher_stat("extension_unusable")
                else:
                    cls._increment_rust_fetcher_stat("extension_empty_or_error")
            except Exception as e:
                logger.warning(f"Error fetching content from {url} with Rust extension: {e}")
                cls._increment_rust_fetcher_stat("extension_empty_or_error")
        elif not cls._rust_fetcher_extension_missing_logged:
            logger.warning(
                "Rust web fetcher extension is unavailable. "
                "Build/install rust_modules/web_fetcher_rs or set WEB_FETCHER_RS_PY_EXT."
            )
            cls._rust_fetcher_extension_missing_logged = True
            cls._increment_rust_fetcher_stat("extension_unavailable")

        return extension_content

    @classmethod
    def _looks_like_blocked_page(cls, text: str) -> bool:
        normalized = normalize_whitespace_text(text).lower()
        if not normalized:
            return False

        if not any(hint in normalized for hint in cls.BLOCKED_PAGE_HINTS):
            return False

        return len(normalized) < cls.MIN_VALID_CONTENT_CHARS * 3

    @classmethod
    def _is_usable_content(cls, text: str) -> bool:
        normalized = normalize_whitespace_text(text)
        if len(normalized) < cls.MIN_VALID_CONTENT_CHARS:
            return False
        if cls._looks_like_blocked_page(normalized):
            return False
        return True

    @classmethod
    async def fetch_content(cls, url: str, timeout: int = 10) -> Optional[str]:
        """
        Fetch and extract the main content from a webpage.

        Args:
            url: The URL to fetch content from
            timeout: Request timeout in seconds

        Returns:
            Extracted text content or None if fetching fails
        """
        normalized_timeout = max(5, timeout)

        rust_content = await cls._fetch_with_rust(url, normalized_timeout)
        if cls._is_usable_content(rust_content):
            return rust_content

        if not rust_content:
            return None

        if cls._looks_like_blocked_page(rust_content):
            return None

        return cls._trim_output(rust_content)

    @classmethod
    async def fetch_content_batch(
        cls,
        urls: List[str],
        timeout: int = 10,
    ) -> Dict[str, str]:
        if not urls:
            return {}

        normalized_timeout = max(5, timeout)
        deduped_urls: List[str] = []
        seen_urls: set[str] = set()
        for raw_url in urls:
            candidate = str(raw_url or "").strip()
            if not candidate or candidate in seen_urls:
                continue
            seen_urls.add(candidate)
            deduped_urls.append(candidate)

        if not deduped_urls:
            return {}

        return await cls._fetch_many_with_rust(deduped_urls, normalized_timeout)


class WebSearch(BaseTool):
    """Search the web for information using various search engines."""

    name: str = "web_search"
    description: str = """Search the web for real-time information about any topic.
    This tool returns comprehensive search results with relevant information, URLs, titles, and descriptions.
    Search fallback and retry behavior is intentionally minimal to keep response latency low."""
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(required) The search query to submit to the search engine.",
            },
            "num_results": {
                "type": "integer",
                "description": "(optional) The number of search results to return. Default is 5.",
                "default": 5,
            },
            "lang": {
                "type": "string",
                "description": "(optional) Language code for search results (default: en).",
                "default": "en",
            },
            "country": {
                "type": "string",
                "description": "(optional) Country code for search results (default: us).",
                "default": "us",
            },
            "fetch_content": {
                "type": "boolean",
                "description": "(optional) Whether to fetch full content from result pages. Default is false.",
                "default": False,
            },
        },
        "required": ["query"],
    }
    content_fetcher: WebContentFetcher = WebContentFetcher()

    @classmethod
    def _search_engines(cls) -> Dict[str, WebSearchEngine]:
        global _SEARCH_ENGINE_CACHE
        if _SEARCH_ENGINE_CACHE is None:
            _SEARCH_ENGINE_CACHE = _build_search_engine_map()
        return _SEARCH_ENGINE_CACHE

    async def execute(
        self,
        query: str,
        num_results: int = 5,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        fetch_content: bool = False,
    ) -> SearchResponse:
        """
        Execute a Web search and return detailed search results.

        Args:
            query: The search query to submit to the search engine
            num_results: The number of search results to return (default: 5)
            lang: Language code for search results (default from config)
            country: Country code for search results (default from config)
            fetch_content: Whether to fetch content from result pages (default: False)

        Returns:
            A structured response containing search results and metadata
        """
        # Get settings from config
        retry_delay = (
            getattr(config.search_config, "retry_delay", 60)
            if config.search_config
            else 60
        )
        max_retries = (
            getattr(config.search_config, "max_retries", 3)
            if config.search_config
            else 3
        )
        retry_delay = max(0, int(retry_delay))
        max_retries = max(0, int(max_retries))

        # Use config values for lang and country if not specified
        if lang is None:
            lang = (
                getattr(config.search_config, "lang", "en")
                if config.search_config
                else "en"
            )

        if country is None:
            country = (
                getattr(config.search_config, "country", "us")
                if config.search_config
                else "us"
            )

        search_params = {"lang": lang, "country": country}

        # Try searching with retries when all engines fail
        for retry_count in range(max_retries + 1):
            results = await self._try_all_engines(query, num_results, search_params)

            if results:
                # Fetch content if requested
                if fetch_content:
                    results = await self._fetch_content_for_results(results)

                # Return a successful structured response
                return SearchResponse(
                    status="success",
                    query=query,
                    results=results,
                    metadata=SearchMetadata(
                        total_results=len(results),
                        language=lang,
                        country=country,
                    ),
                )

            if retry_count < max_retries:
                # All engines failed, wait and retry
                logger.warning(
                    f"All search engines failed. Waiting {retry_delay} seconds before retry {retry_count + 1}/{max_retries}..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    f"All search engines failed after {max_retries} retries. Giving up."
                )

        # Return an error response
        return SearchResponse(
            query=query,
            error="All search engines failed to return results after multiple retries.",
            results=[],
        )

    async def _try_all_engines(
        self, query: str, num_results: int, search_params: Dict[str, Any]
    ) -> List[SearchResult]:
        """Try all search engines in the configured order."""
        engine_order = self._get_engine_order()
        failed_engines = []

        engines = self._search_engines()
        for engine_name in engine_order:
            engine = engines.get(engine_name)
            if engine is None:
                failed_engines.append(engine_name)
                continue
            logger.info(f"🔎 Attempting search with {engine_name.capitalize()}...")
            search_items = await self._perform_search_with_engine(
                engine, query, num_results, search_params
            )

            if not search_items:
                failed_engines.append(engine_name)
                continue

            if failed_engines:
                logger.info(
                    f"Search successful with {engine_name.capitalize()} after trying: {', '.join(failed_engines)}"
                )

            # Transform search items into structured results
            return [
                SearchResult(
                    position=i + 1,
                    url=item.url,
                    title=item.title
                    or f"Result {i+1}",  # Ensure we always have a title
                    description=item.description or "",
                    source=engine_name,
                )
                for i, item in enumerate(search_items)
            ]

        if failed_engines:
            logger.error(f"All search engines failed: {', '.join(failed_engines)}")
        return []

    async def _fetch_content_for_results(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """Fetch and add web content to search results."""
        if not results:
            return []

        fetch_timeout = (
            int(getattr(config.search_config, "fetch_timeout", 10))
            if config.search_config
            else 10
        )
        fetch_timeout = max(5, fetch_timeout)

        urls = [result.url for result in results if result.url]
        content_by_url = await self.content_fetcher.fetch_content_batch(
            urls,
            timeout=fetch_timeout,
        )

        pending_results: List[SearchResult] = []
        for result in results:
            if not result.url:
                continue

            rust_content = content_by_url.get(result.url)
            if rust_content:
                result.raw_content = rust_content
                continue

            pending_results.append(result)

        if pending_results:
            tasks = [self._fetch_single_result_content(result) for result in pending_results]
            await asyncio.gather(*tasks)

        return results

    async def _fetch_single_result_content(self, result: SearchResult) -> SearchResult:
        """Fetch content for a single search result."""
        if result.url:
            content = await self.content_fetcher.fetch_content(result.url)
            if content:
                result.raw_content = content
        return result

    def _get_engine_order(self) -> List[str]:
        """Determines the order in which to try search engines."""
        preferred = (
            getattr(config.search_config, "engine", "google").lower()
            if config.search_config
            else "google"
        )
        fallbacks = (
            [engine.lower() for engine in config.search_config.fallback_engines]
            if config.search_config
            and hasattr(config.search_config, "fallback_engines")
            else []
        )

        # Start with preferred engine, then configured fallbacks only.
        engines = self._search_engines()
        engine_order = [preferred] if preferred in engines else []
        engine_order.extend([fb for fb in fallbacks if fb in engines and fb not in engine_order])

        if not engine_order:
            return list(engines.keys()) or ["duckduckgo"]
        return engine_order

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def _perform_search_with_engine(
        self,
        engine: WebSearchEngine,
        query: str,
        num_results: int,
        search_params: Dict[str, Any],
    ) -> List[SearchItem]:
        """Execute search with the given engine and parameters."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: list(
                engine.perform_search(
                    query,
                    num_results=num_results,
                    lang=search_params.get("lang"),
                    country=search_params.get("country"),
                )
            ),
        )


if __name__ == "__main__":
    web_search = WebSearch()
    search_response = asyncio.run(
        web_search.execute(
            query="Python programming", fetch_content=True, num_results=1
        )
    )
    print(search_response.to_tool_result())
