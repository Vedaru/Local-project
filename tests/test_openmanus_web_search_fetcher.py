import asyncio
import importlib.machinery
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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


def test_fetch_content_batch_uses_rust_batch_extension(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    class _BatchExtensionModule:
        @staticmethod
        def fetch_content_batch(urls, _timeout, _max_chars):
            return [
                (True, f"Rust extension article body {index} " * 30, None)
                for index, _ in enumerate(urls)
            ]

    monkeypatch.setattr(
        WebContentFetcher,
        "_load_rust_fetcher_module",
        classmethod(lambda cls: _BatchExtensionModule()),
    )

    url_list = ["https://example.com/a", "https://example.com/b"]
    payload = asyncio.run(WebContentFetcher.fetch_content_batch(url_list, timeout=10))

    assert set(payload.keys()) == set(url_list)
    assert "Rust extension article body" in payload["https://example.com/a"]

    stats = WebContentFetcher.get_rust_fetcher_stats()
    assert stats["requests"] == 2
    assert stats["extension_attempts"] == 2
    assert stats["extension_success"] == 2


def test_fetch_content_for_results_uses_batch_then_fallback(monkeypatch):
    web_search = WebSearch()
    batch_content = "batch rust content " * 30
    fallback_content = "fallback single content " * 30
    fallback_calls = {"count": 0}

    async def fake_batch(cls, urls, timeout=10):
        assert timeout >= 5
        return {urls[0]: batch_content}

    async def fake_single(result):
        fallback_calls["count"] += 1
        result.raw_content = fallback_content
        return result

    monkeypatch.setattr(WebContentFetcher, "fetch_content_batch", classmethod(fake_batch))
    monkeypatch.setattr(web_search, "_fetch_single_result_content", fake_single)

    results = [
        web_search_module.SearchResult(
            position=1,
            url="https://example.com/1",
            title="Result 1",
            description="",
            source="test",
        ),
        web_search_module.SearchResult(
            position=2,
            url="https://example.com/2",
            title="Result 2",
            description="",
            source="test",
        ),
    ]

    enriched = asyncio.run(web_search._fetch_content_for_results(results))

    assert enriched[0].raw_content == batch_content
    assert enriched[1].raw_content == fallback_content
    assert fallback_calls["count"] == 1


def test_fetch_content_batch_local_http_e2e(monkeypatch):
    _reset_fetcher_runtime_state(monkeypatch)

    # Avoid localhost traffic being routed through system proxy in this environment.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    rust_module = WebContentFetcher._load_rust_fetcher_module()
    if rust_module is None or not hasattr(rust_module, "fetch_content_batch"):
        pytest.skip("Rust web fetcher extension is unavailable")

    article_a = "Rust local e2e article A. " * 20
    article_b = "Rust local e2e article B. " * 20
    pages = {
        "/a": f"<html><body><main><article>{article_a}</article></main></body></html>",
        "/b": f"<html><body><main><article>{article_b}</article></main></body></html>",
    }

    class _LocalHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"not found")
                return

            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        urls = [f"{base}/a", f"{base}/b"]

        payload = asyncio.run(WebContentFetcher.fetch_content_batch(urls, timeout=10))
        assert set(payload.keys()) == set(urls)
        assert len(payload[urls[0]]) > 220
        assert len(payload[urls[1]]) > 220

        web_search = WebSearch()
        seeded_results = [
            web_search_module.SearchResult(
                position=1,
                url=urls[0],
                title="Result A",
                description="",
                source="test",
            ),
            web_search_module.SearchResult(
                position=2,
                url=urls[1],
                title="Result B",
                description="",
                source="test",
            ),
        ]
        enriched = asyncio.run(web_search._fetch_content_for_results(seeded_results))
        assert all(result.raw_content and len(result.raw_content) > 220 for result in enriched)
    finally:
        server.shutdown()
        server.server_close()


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
