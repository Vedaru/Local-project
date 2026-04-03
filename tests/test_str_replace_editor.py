import asyncio
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest

# pre-create a minimal stub for the `browser_use` package which is imported by
# app.tool.browser_use_tool. The real package isn't installed in the test
# environment, so we provide dummy attributes to keep imports happy.

browser_pkg = types.ModuleType("browser_use")
browser_pkg.Browser = object
browser_pkg.BrowserConfig = object

# nested submodules used by browser_use_tool
browser_browser = types.ModuleType("browser_use.browser")
browser_context = types.ModuleType("browser_use.browser.context")
browser_context.BrowserContext = object
browser_context.BrowserContextConfig = object
browser_dom = types.ModuleType("browser_use.dom")
browser_dom_service = types.ModuleType("browser_use.dom.service")
browser_dom_service.DomService = object

# register stubs
sys.modules["browser_use"] = browser_pkg
sys.modules["browser_use.browser"] = browser_browser
sys.modules["browser_use.browser.context"] = browser_context
sys.modules["browser_use.dom"] = browser_dom
sys.modules["browser_use.dom.service"] = browser_dom_service

# ensure project root is on sys.path like other tests
sys.path.insert(0, str(Path(__file__).parent.parent))
# also add the openmanus/app directory so `import app` resolves correctly
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "openmanus"))

# create stubs for third-party libraries that aren't installed in the
# test environment but are imported by modules under test

# tiktoken is imported by app.llm
tiktoken_stub = types.ModuleType("tiktoken")
tiktoken_stub.__spec__ = importlib.machinery.ModuleSpec("tiktoken", loader=None)
sys.modules["tiktoken"] = tiktoken_stub
# loguru is imported by app.logger
loguru_stub = types.ModuleType("loguru")


# provide a dummy logger object with basic interface
class DummyLogger:
    def __getattr__(self, name):
        def _(*args, **kwargs):
            pass

        return _


loguru_stub.logger = DummyLogger()
sys.modules["loguru"] = loguru_stub

# dynamically load the str_replace_editor module without pulling in the rest
# of the `app.tool` package (which has many heavyweight dependencies).
str_path = Path(__file__).parent.parent / "modules" / "openmanus" / "app" / "tool" / "str_replace_editor.py"
spec = importlib.util.spec_from_file_location("str_replace_editor_test", str_path)
module = importlib.util.module_from_spec(spec)
sys.modules["str_replace_editor_test"] = module
spec.loader.exec_module(module)  # type: ignore
StrReplaceEditor = module.StrReplaceEditor

# we still need a file operator for running commands
from modules.openmanus.app.tool.file_operators import LocalFileOperator  # noqa: E402
from app.exceptions import ToolError  # noqa: E402


def test_view_directory_skips_hidden(tmp_path):
    """The directory viewer should list paths up to two levels deep and
    ignore items whose names begin with a dot (hidden files/directories).
    """
    base = tmp_path / "root"
    base.mkdir()

    # create a top-level file and directory
    (base / "file1.txt").write_text("content")
    sub = base / "subdir"
    sub.mkdir()
    (sub / "file2.txt").write_text("more")

    # create some hidden items that should be excluded
    (base / ".hidden_dir").mkdir()
    (sub / ".hidden_file.txt").write_text("secret")

    editor = StrReplaceEditor()
    op = LocalFileOperator()

    result = asyncio.run(editor._view_directory(str(base), op))

    output = result.output
    assert "file1.txt" in output
    assert "subdir" in output
    assert "file2.txt" in output
    assert ".hidden_dir" not in output
    assert ".hidden_file.txt" not in output
    assert result.error == ""


def test_view_binary_office_file_is_blocked(tmp_path):
    """Viewing binary Office files should fail fast with actionable guidance."""
    file_path = tmp_path / "sample.docx"
    file_path.write_bytes(b"PK\x03\x04fake-docx")

    editor = StrReplaceEditor()

    with pytest.raises(ToolError) as exc:
        asyncio.run(editor.execute(command="view", path=str(file_path)))

    message = str(exc.value.message)
    assert "binary Office file" in message
    assert "python_execute" in message


def test_create_binary_office_file_is_blocked(tmp_path):
    """Creating binary Office files as plain text should be rejected."""
    file_path = tmp_path / "new_presentation.pptx"

    editor = StrReplaceEditor()

    with pytest.raises(ToolError) as exc:
        asyncio.run(
            editor.execute(
                command="create",
                path=str(file_path),
                file_text="plain text content",
            )
        )

    message = str(exc.value.message)
    assert "binary Office file" in message
    assert "python_execute" in message
