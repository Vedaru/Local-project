import asyncio
import importlib.machinery
import sys
import types
from pathlib import Path


if "loguru" not in sys.modules:
    loguru_stub = types.ModuleType("loguru")

    class _DummyLogger:
        def __getattr__(self, _name):
            def _noop(*args, **kwargs):
                return None

            return _noop

    loguru_stub.logger = _DummyLogger()
    loguru_stub.__spec__ = importlib.machinery.ModuleSpec("loguru", loader=None)
    sys.modules["loguru"] = loguru_stub

if "googlesearch" not in sys.modules:
    googlesearch_stub = types.ModuleType("googlesearch")
    googlesearch_stub.search = lambda *args, **kwargs: []
    googlesearch_stub.__spec__ = importlib.machinery.ModuleSpec(
        "googlesearch", loader=None
    )
    sys.modules["googlesearch"] = googlesearch_stub

if "duckduckgo_search" not in sys.modules:
    duckduckgo_stub = types.ModuleType("duckduckgo_search")

    class _DummyDDGS:
        def text(self, *args, **kwargs):
            return []

    duckduckgo_stub.DDGS = _DummyDDGS
    duckduckgo_stub.__spec__ = importlib.machinery.ModuleSpec(
        "duckduckgo_search", loader=None
    )
    sys.modules["duckduckgo_search"] = duckduckgo_stub

if "baidusearch" not in sys.modules:
    baidusearch_pkg = types.ModuleType("baidusearch")
    baidusearch_mod = types.ModuleType("baidusearch.baidusearch")
    baidusearch_mod.search = lambda *args, **kwargs: []
    baidusearch_pkg.baidusearch = baidusearch_mod
    baidusearch_pkg.__spec__ = importlib.machinery.ModuleSpec(
        "baidusearch", loader=None
    )
    baidusearch_mod.__spec__ = importlib.machinery.ModuleSpec(
        "baidusearch.baidusearch", loader=None
    )
    sys.modules["baidusearch"] = baidusearch_pkg
    sys.modules["baidusearch.baidusearch"] = baidusearch_mod


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "modules" / "openmanus"))

from modules.openmanus.app.tool import web_search as web_search_module  # noqa: E402
from modules.openmanus.app.tool.web_search import WebContentFetcher, WebSearch  # noqa: E402


def _reset_fetcher_runtime_state(monkeypatch):
    monkeypatch.setattr(WebContentFetcher, "_rust_fetcher_module_cache", None)
    monkeypatch.setattr(WebContentFetcher, "_rust_fetcher_module_attempted", False)
    monkeypatch.setattr(WebContentFetcher, "_rust_fetcher_extension_missing_logged", False)
    WebContentFetcher.reset_rust_fetcher_stats()


def test_fetch_content_returns_none_when_rust_returns_empty(monkeypatch):
    async def fake_rust(cls, _url, _timeout):
        return ""

    monkeypatch.setattr(
        WebContentFetcher,
        "_fetch_with_rust",
        classmethod(fake_rust),
    )

    output = asyncio.run(WebContentFetcher.fetch_content("https://example.com"))
    assert output is None


def test_fetch_content_returns_none_for_block_page_candidates(monkeypatch):
    async def fake_rust(cls, _url, _timeout):
        return "captcha verify request blocked"

    monkeypatch.setattr(
        WebContentFetcher,
        "_fetch_with_rust",
        classmethod(fake_rust),
    )

    output = asyncio.run(WebContentFetcher.fetch_content("https://example.com"))
    assert output is None


def test_fetch_content_prefers_rust_when_usable(monkeypatch):
    call_count = {"rust": 0}

    async def fake_rust(cls, _url, _timeout):
        call_count["rust"] += 1
        return "Rust extracted article body " * 40

    monkeypatch.setattr(
        WebContentFetcher,
        "_fetch_with_rust",
        classmethod(fake_rust),
    )

    output = asyncio.run(WebContentFetcher.fetch_content("https://example.com"))

    assert output is not None
    assert "Rust extracted article body" in output
    assert call_count["rust"] == 1


def test_fetch_content_returns_best_effort_for_short_non_blocked_text(monkeypatch):
    short_content = "brief summary without blocked keywords"

    async def fake_rust(cls, _url, _timeout):
        return short_content

    monkeypatch.setattr(
        WebContentFetcher,
        "_fetch_with_rust",
        classmethod(fake_rust),
    )

    output = asyncio.run(WebContentFetcher.fetch_content("https://example.com"))
    assert output == short_content


def test_candidate_extension_paths_accepts_env_file(monkeypatch, tmp_path):
    _reset_fetcher_runtime_state(monkeypatch)

    fake_extension = tmp_path / "_web_fetcher_rs.cp311-win_amd64.pyd"
    fake_extension.write_text("placeholder", encoding="utf-8")

    monkeypatch.setenv(WebContentFetcher.RUST_FETCHER_EXT_ENV, str(fake_extension))
    monkeypatch.setattr(
        WebContentFetcher,
        "_project_root",
        classmethod(lambda cls: tmp_path),
    )

    candidates = WebContentFetcher._candidate_extension_paths()

    assert fake_extension.resolve() in candidates


def test_fetch_with_rust_prefers_extension(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    class _ExtensionModule:
        @staticmethod
        def fetch_content(_url, _timeout, _max_chars):
            return (True, "Rust extension article body " * 30, None)

    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: _ExtensionModule()),
    )

    output = asyncio.run(WebContentFetcher._fetch_with_rust("https://example.com", 10))

    assert "Rust extension article body" in output


def test_fetch_with_rust_returns_empty_when_extension_empty(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        WebContentFetcher,
        "_run_rust_extension_sync",
        classmethod(lambda cls, _module, _url, _timeout: ""),
    )

    output = asyncio.run(WebContentFetcher._fetch_with_rust("https://example.com", 10))

    assert output == ""


def test_fetch_with_rust_returns_empty_when_extension_raises(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    class _BrokenExtensionModule:
        @staticmethod
        def fetch_content(_url, _timeout, _max_chars):
            raise RuntimeError("extension failed")

    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: _BrokenExtensionModule()),
    )

    output = asyncio.run(WebContentFetcher._fetch_with_rust("https://example.com", 10))

    assert output == ""
    stats = WebContentFetcher.get_rust_fetcher_stats()
    assert stats["extension_attempts"] == 1
    assert stats["extension_empty_or_error"] == 1


def test_fetch_with_rust_records_extension_unavailable(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)
    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: None),
    )

    output = asyncio.run(WebContentFetcher._fetch_with_rust("https://example.com", 10))

    assert output == ""
    stats = WebContentFetcher.get_rust_fetcher_stats()
    assert stats["requests"] == 1
    assert stats["extension_unavailable"] == 1


def test_fetch_with_rust_stats_record_extension_success(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    class _ExtensionModule:
        @staticmethod
        def fetch_content(_url, _timeout, _max_chars):
            return (True, "Rust extension article body " * 20, None)

    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: _ExtensionModule()),
    )

    output = asyncio.run(WebContentFetcher._fetch_with_rust("https://example.com", 10))

    assert "Rust extension article body" in output
    stats = WebContentFetcher.get_rust_fetcher_stats()
    assert stats["requests"] == 1
    assert stats["extension_attempts"] == 1
    assert stats["extension_success"] == 1


def test_get_engine_order_uses_configured_engines_only(monkeypatch):
    class _FakeSearchConfig:
        engine = "google"
        fallback_engines = ["bing"]

    monkeypatch.setattr(
        web_search_module,
        "config",
        types.SimpleNamespace(search_config=_FakeSearchConfig()),
    )

    tool = WebSearch()
    assert tool._get_engine_order() == ["google", "bing"]