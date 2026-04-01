import asyncio
import importlib.machinery
import json
import sys
import types
from pathlib import Path


class _DummyLogger:
    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None

        return _noop


# Keep tests independent from optional runtime dependencies.
if "mcp" not in sys.modules:
    mcp_stub = types.ModuleType("mcp")

    class _DummyClientSession:
        pass

    class _DummyStdioServerParameters:
        def __init__(self, *args, **kwargs):
            pass

    mcp_stub.ClientSession = _DummyClientSession
    mcp_stub.StdioServerParameters = _DummyStdioServerParameters

    mcp_client = types.ModuleType("mcp.client")
    mcp_sse = types.ModuleType("mcp.client.sse")
    mcp_stdio = types.ModuleType("mcp.client.stdio")

    mcp_sse.sse_client = lambda *args, **kwargs: None
    mcp_stdio.stdio_client = lambda *args, **kwargs: None

    mcp_types = types.ModuleType("mcp.types")

    class _DummyListToolsResult:
        pass

    class _DummyTextContent:
        pass

    mcp_types.ListToolsResult = _DummyListToolsResult
    mcp_types.TextContent = _DummyTextContent

    sys.modules["mcp"] = mcp_stub
    sys.modules["mcp.client"] = mcp_client
    sys.modules["mcp.client.sse"] = mcp_sse
    sys.modules["mcp.client.stdio"] = mcp_stdio
    sys.modules["mcp.types"] = mcp_types

if "loguru" not in sys.modules:
    loguru_stub = types.ModuleType("loguru")
    loguru_stub.logger = _DummyLogger()
    sys.modules["loguru"] = loguru_stub

if "tiktoken" not in sys.modules:
    tiktoken_stub = types.ModuleType("tiktoken")

    class _DummyEncoding:
        def encode(self, text):
            return list(text.encode("utf-8"))

    tiktoken_stub.encoding_for_model = lambda _model: _DummyEncoding()
    tiktoken_stub.get_encoding = lambda _name: _DummyEncoding()
    tiktoken_stub.__spec__ = importlib.machinery.ModuleSpec("tiktoken", loader=None)
    sys.modules["tiktoken"] = tiktoken_stub

if "browser_use" not in sys.modules:
    browser_pkg = types.ModuleType("browser_use")

    class _DummyBrowser:
        pass

    class _DummyBrowserConfig:
        def __init__(self, *args, **kwargs):
            pass

    browser_pkg.Browser = _DummyBrowser
    browser_pkg.BrowserConfig = _DummyBrowserConfig

    browser_browser = types.ModuleType("browser_use.browser")
    browser_context = types.ModuleType("browser_use.browser.context")

    class _DummyBrowserContext:
        pass

    class _DummyBrowserContextConfig:
        def __init__(self, *args, **kwargs):
            pass

    browser_context.BrowserContext = _DummyBrowserContext
    browser_context.BrowserContextConfig = _DummyBrowserContextConfig

    browser_dom = types.ModuleType("browser_use.dom")
    browser_dom_service = types.ModuleType("browser_use.dom.service")

    class _DummyDomService:
        def __init__(self, *args, **kwargs):
            pass

    browser_dom_service.DomService = _DummyDomService

    sys.modules["browser_use"] = browser_pkg
    sys.modules["browser_use.browser"] = browser_browser
    sys.modules["browser_use.browser.context"] = browser_context
    sys.modules["browser_use.dom"] = browser_dom
    sys.modules["browser_use.dom.service"] = browser_dom_service

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "modules" / "openmanus"))

from modules.openmanus.app.agent.browser import BrowserContextHelper  # noqa: E402
from modules.openmanus.app.tool.browser_use_tool import BrowserUseTool  # noqa: E402


class _DummyTab:
    def model_dump(self):
        return {"id": 0, "title": "Example", "url": "https://example.com"}


class _DummyElementTree:
    def clickable_elements_to_string(self):
        return "[0]<a>Example</a>"


class _DummyViewportInfo:
    height = 720


class _DummyState:
    url = "https://example.com"
    title = "Example"
    tabs = [_DummyTab()]
    element_tree = _DummyElementTree()
    pixels_above = 10
    pixels_below = 20
    viewport_info = _DummyViewportInfo()


class _DummyPage:
    url = "https://example.com"

    def __init__(self, page_text: str):
        self._page_text = page_text

    async def bring_to_front(self):
        return None

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def screenshot(self, *args, **kwargs):
        return b"jpeg-bytes"

    async def evaluate(self, _script):
        return self._page_text


class _DummyContext:
    def __init__(self, page_text: str):
        self._page = _DummyPage(page_text)
        self.config = types.SimpleNamespace(browser_window_size={"height": 720})

    async def get_state(self, *args, **kwargs):
        return _DummyState()

    async def get_current_page(self):
        return self._page


class _DummyToolCollection:
    def get_tool(self, _name):
        return None


class _DummyMemory:
    def __init__(self):
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)


class _DummyAgent:
    def __init__(self):
        self.available_tools = _DummyToolCollection()
        self.memory = _DummyMemory()


def test_split_text_into_chunks_with_overlap():
    text = "abcdefghijklmnopqrstuvwxyz"
    chunks = BrowserUseTool._split_text_into_chunks(text, chunk_size=10, overlap=2)
    assert chunks == ["abcdefghij", "ijklmnopqr", "qrstuvwxyz"]


def test_build_text_preview_preserves_head_and_tail():
    text = ("A" * 40) + ("B" * 40)
    preview = BrowserUseTool._build_text_preview(text, max_chars=20)

    assert preview.startswith("A" * 10)
    assert preview.endswith("B" * 10)
    assert "[60 chars omitted]" in preview


def test_normalize_tabs_returns_index_id_and_meta():
    tabs = [
        {"id": 5, "title": "First", "url": "https://a.example"},
        {"page_id": 12, "title": "Second", "url": "https://b.example"},
        {"title": "Third", "url": "https://c.example"},
    ]

    normalized = BrowserUseTool._normalize_tabs(tabs)

    assert normalized[0]["index"] == 0
    assert normalized[0]["id"] == 5
    assert normalized[1]["index"] == 1
    assert normalized[1]["id"] == 12
    assert normalized[2]["index"] == 2
    assert normalized[2]["id"] is None


def test_resolve_tab_switch_index_supports_index_and_id():
    tabs_info = [
        {"index": 0, "id": 10, "title": "A", "url": "a"},
        {"index": 1, "id": 99, "title": "B", "url": "b"},
    ]

    assert BrowserUseTool._resolve_tab_switch_index(tabs_info, 1) == 1
    assert BrowserUseTool._resolve_tab_switch_index(tabs_info, 99) == 1
    assert BrowserUseTool._resolve_tab_switch_index(tabs_info, 77) is None


def test_build_click_feedback_detects_home_misclick():
    feedback = BrowserUseTool._build_click_feedback(
        clicked_by="index",
        clicked_value=0,
        element_brief={"tag": "a", "text": "首页", "href": "https://www.bilibili.com/"},
        pre_click_prediction={"likely_effect": "navigate"},
        switched_tab=None,
        before_summary={"url": "https://www.bilibili.com/c/kichiku/", "tab_count": 1},
        after_summary={"url": "https://www.bilibili.com/", "tab_count": 1},
    )

    assert feedback["outcome"] == "likely_misclick"
    assert feedback["signals"]["is_home_nav"] is True
    assert feedback["signals"]["likely_misclick"] is True


def test_build_click_feedback_detects_no_progress_click():
    feedback = BrowserUseTool._build_click_feedback(
        clicked_by="index",
        clicked_value=15,
        element_brief={"tag": "li", "text": "动态", "href": ""},
        pre_click_prediction={"likely_effect": "low_confidence_click_target"},
        switched_tab=None,
        before_summary={"url": "https://www.bilibili.com/c/kichiku/", "tab_count": 1},
        after_summary={"url": "https://www.bilibili.com/c/kichiku/", "tab_count": 1},
    )

    assert feedback["outcome"] == "no_progress"
    assert feedback["signals"]["no_progress"] is True


def test_predict_click_effect_for_navigation_link():
    prediction = BrowserUseTool._predict_click_effect(
        "https://www.bilibili.com/c/kichiku/",
        {
            "tag": "a",
            "text": "视频卡片",
            "href": "https://www.bilibili.com/video/BV1xx411c7mD",
            "target": "",
        },
    )

    assert prediction["likely_effect"] == "navigate"
    assert prediction["has_link"] is True
    assert prediction["is_home_navigation"] is False


def test_predict_click_effect_for_blank_link_and_home_nav():
    prediction = BrowserUseTool._predict_click_effect(
        "https://www.bilibili.com/c/kichiku/",
        {
            "tag": "a",
            "text": "首页",
            "href": "https://www.bilibili.com/",
            "target": "_blank",
        },
    )

    assert prediction["opens_new_tab"] is True
    assert prediction["is_home_navigation"] is True


def test_predict_click_effect_for_low_confidence_target():
    prediction = BrowserUseTool._predict_click_effect(
        "https://www.bilibili.com/c/kichiku/",
        {
            "tag": "div",
            "text": "",
            "href": "",
            "target": "",
        },
    )

    assert prediction["likely_effect"] == "low_confidence_click_target"


def test_get_current_state_contains_text_length_and_preview():
    tool = BrowserUseTool(llm=None)
    full_text = ("A" * 2500) + ("B" * 2500)
    context = _DummyContext(page_text=full_text)

    result = asyncio.run(tool.get_current_state(context))

    assert not result.error
    payload = json.loads(result.output)
    assert payload["page_text_length"] == len(full_text)
    assert "chars omitted" in payload["page_text"]


def test_browser_context_helper_reads_scroll_info_from_state():
    helper = BrowserContextHelper(_DummyAgent())

    async def fake_get_browser_state():
        return {
            "url": "https://example.com",
            "title": "Example",
            "tabs": [
                {
                    "index": 0,
                    "id": 0,
                    "title": "Main",
                    "url": "https://example.com",
                },
                {
                    "index": 1,
                    "id": 7,
                    "title": "Popup",
                    "url": "https://popup.example.com",
                },
            ],
            "scroll_info": {"pixels_above": 120, "pixels_below": 340},
            "page_text": "hello world",
            "page_text_length": 11,
        }

    helper.get_browser_state = fake_get_browser_state  # type: ignore[method-assign]
    prompt = asyncio.run(helper.format_next_step_prompt())

    assert "(120 pixels)" in prompt
    assert "(340 pixels)" in prompt
    assert "Page text preview (11 chars total)" in prompt
    assert "index=1, id=7" in prompt
