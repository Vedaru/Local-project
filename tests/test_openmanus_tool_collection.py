"""Unit tests for OpenManus tool collection scheduling and error handling."""

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

# Ensure `import app` resolves to modules/openmanus/app
sys.path.insert(0, str(Path(__file__).parent.parent / "modules" / "openmanus"))

from modules.openmanus.app.tool.base import BaseTool, ToolResult
from modules.openmanus.app.tool.tool_collection import ToolCollection


class _DummyTool(BaseTool):
    name: str
    description: str = "dummy"

    async def execute(self, **kwargs):
        if kwargs.get("raise_tool_error"):
            tool_error_type = importlib.import_module("app.exceptions").ToolError

            raise tool_error_type("dummy tool error")
        if kwargs.get("raise_unexpected"):
            raise RuntimeError("unexpected failure")
        await asyncio.sleep(float(kwargs.get("sleep", 0)))
        value = kwargs.get("value", "ok")
        return ToolResult(output=f"{self.name}:{value}")


@pytest.mark.unit
def test_to_params_cache_records_hits_and_misses():
    collection = ToolCollection(_DummyTool(name="alpha"))

    first = collection.to_params()
    second = collection.to_params()

    assert first == second
    stats = collection.get_stats()
    assert stats["params_cache_misses"] == 1
    assert stats["params_cache_hits"] == 1


@pytest.mark.unit
def test_execute_invalid_tool_returns_failure():
    collection = ToolCollection(_DummyTool(name="alpha"))

    result = asyncio.run(collection.execute(name="missing", tool_input={}))

    assert result.error == "Tool missing is invalid"


@pytest.mark.unit
def test_execute_maps_toolerror_to_failure_result():
    collection = ToolCollection(_DummyTool(name="alpha"))

    result = asyncio.run(collection.execute(name="alpha", tool_input={"raise_tool_error": True}))

    assert result.error == "dummy tool error"
    stats = collection.get_stats()
    assert stats["execute_errors"] == 1


@pytest.mark.unit
def test_execute_maps_unexpected_error_to_failure_result():
    collection = ToolCollection(_DummyTool(name="alpha"))

    result = asyncio.run(collection.execute(name="alpha", tool_input={"raise_unexpected": True}))

    assert result.error and "execution failed" in result.error
    stats = collection.get_stats()
    assert stats["execute_errors"] == 1


@pytest.mark.unit
def test_execute_many_parallel_safe_tools_increment_parallel_stats():
    collection = ToolCollection(_DummyTool(name="alpha"), _DummyTool(name="beta"))

    results = asyncio.run(
        collection.execute_many(
            [
                {"name": "alpha", "tool_input": {"sleep": 0.05, "value": "1"}},
                {"name": "beta", "tool_input": {"sleep": 0.0, "value": "2"}},
            ]
        )
    )

    assert [result.output for result in results] == ["alpha:1", "beta:2"]
    stats = collection.get_stats()
    assert stats["batch_calls"] == 1
    assert stats["batch_parallel_calls"] == 1


@pytest.mark.unit
def test_execute_many_keeps_serial_mode_for_unsafe_tool_names():
    collection = ToolCollection(_DummyTool(name="mcp_tool"), _DummyTool(name="beta"))

    results = asyncio.run(
        collection.execute_many(
            [
                {"name": "mcp_tool", "tool_input": {"value": "1"}},
                {"name": "beta", "tool_input": {"value": "2"}},
            ]
        )
    )

    assert [result.output for result in results] == ["mcp_tool:1", "beta:2"]
    stats = collection.get_stats()
    assert stats["batch_calls"] == 1
    assert stats["batch_parallel_calls"] == 0
