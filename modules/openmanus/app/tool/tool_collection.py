"""Collection classes for managing multiple tools."""
import asyncio
import os
import time
from typing import Any, Dict, List

from app.exceptions import ToolError
from app.logger import logger
from app.tool.base import BaseTool, ToolFailure, ToolResult


class ToolCollection:
    """A collection of defined tools."""

    DEFAULT_SERIAL_TOOL_NAMES = frozenset(
        {
            "bash",
            "browser_use",
            "str_replace_editor",
            "python_execute",
            "memory_md",
            "mcp",
            "ask_human",
            "terminate",
        }
    )

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, *tools: BaseTool):
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self._params_cache: List[Dict[str, Any]] | None = None

        self.parallel_execution_enabled = self._read_bool_env(
            "OPENMANUS_TOOL_PARALLEL_ENABLED", default=True
        )
        self.parallel_max_workers = max(
            1,
            int((os.getenv("OPENMANUS_TOOL_PARALLEL_MAX", "4") or "4").strip() or "4"),
        )
        self.serial_tool_names = set(self.DEFAULT_SERIAL_TOOL_NAMES)

        self._stats: Dict[str, Any] = {
            "execute_calls": 0,
            "execute_errors": 0,
            "batch_calls": 0,
            "batch_parallel_calls": 0,
            "params_cache_hits": 0,
            "params_cache_misses": 0,
            "total_execute_latency_ms": 0.0,
        }

    @staticmethod
    def _read_bool_env(env_name: str, default: bool) -> bool:
        raw = os.getenv(env_name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _invalidate_params_cache(self) -> None:
        self._params_cache = None

    def _is_parallel_safe_tool(self, name: str) -> bool:
        lowered = (name or "").strip().lower()
        if not lowered:
            return False
        if lowered.startswith("mcp_"):
            return False
        return lowered not in self.serial_tool_names

    def __iter__(self):
        return iter(self.tools)

    def to_params(self) -> List[Dict[str, Any]]:
        if self._params_cache is not None:
            self._stats["params_cache_hits"] = int(self._stats["params_cache_hits"]) + 1
            return list(self._params_cache)

        self._stats["params_cache_misses"] = int(self._stats["params_cache_misses"]) + 1
        self._params_cache = [tool.to_param() for tool in self.tools]
        return list(self._params_cache)

    async def execute(
        self, *, name: str, tool_input: Dict[str, Any] = None
    ) -> ToolResult:
        started = time.perf_counter()
        self._stats["execute_calls"] = int(self._stats["execute_calls"]) + 1

        tool = self.tool_map.get(name)
        if not tool:
            self._stats["execute_errors"] = int(self._stats["execute_errors"]) + 1
            return ToolFailure(error=f"Tool {name} is invalid")

        try:
            from modules.security_tools import is_tool_allowed
        except ImportError:

            def is_tool_allowed(_tool: str) -> bool:  # type: ignore[misc]
                return True

        if not is_tool_allowed(name):
            self._stats["execute_errors"] = int(self._stats["execute_errors"]) + 1
            return ToolFailure(error=f"Tool {name} is disabled by security policy")

        input_payload = tool_input or {}
        try:
            result = await tool(**input_payload)
            return result
        except ToolError as e:
            self._stats["execute_errors"] = int(self._stats["execute_errors"]) + 1
            return ToolFailure(error=e.message)
        except Exception as e:
            self._stats["execute_errors"] = int(self._stats["execute_errors"]) + 1
            logger.exception(f"Tool {name} failed with unexpected error: {e}")
            return ToolFailure(error=f"Tool {name} execution failed: {str(e)}")
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._stats["total_execute_latency_ms"] = float(
                self._stats["total_execute_latency_ms"]
            ) + float(elapsed_ms)

    async def execute_many(self, calls: List[Dict[str, Any]]) -> List[ToolResult]:
        """Execute multiple tool calls.

        Parallel mode is enabled only when:
        - global parallel flag is enabled,
        - there are at least 2 calls,
        - all involved tools are marked as parallel-safe.
        """
        self._stats["batch_calls"] = int(self._stats["batch_calls"]) + 1

        normalized_calls: List[tuple[str, Dict[str, Any]]] = []
        for call in calls or []:
            name = str(call.get("name") or "").strip()
            tool_input = call.get("tool_input") or {}
            normalized_calls.append((name, tool_input))

        if not normalized_calls:
            return []

        should_parallel = (
            self.parallel_execution_enabled
            and len(normalized_calls) > 1
            and all(self._is_parallel_safe_tool(name) for name, _ in normalized_calls)
        )

        if not should_parallel:
            results: List[ToolResult] = []
            for name, tool_input in normalized_calls:
                results.append(await self.execute(name=name, tool_input=tool_input))
            return results

        self._stats["batch_parallel_calls"] = int(self._stats["batch_parallel_calls"]) + 1
        semaphore = asyncio.Semaphore(max(1, int(self.parallel_max_workers)))

        async def _run_one(
            index: int,
            tool_name: str,
            tool_input: Dict[str, Any],
        ) -> tuple[int, ToolResult]:
            async with semaphore:
                result = await self.execute(name=tool_name, tool_input=tool_input)
                return index, result

        gathered = await asyncio.gather(
            *[
                _run_one(index, name, tool_input)
                for index, (name, tool_input) in enumerate(normalized_calls)
            ]
        )

        gathered.sort(key=lambda item: item[0])
        return [result for _, result in gathered]

    async def execute_all(self) -> List[ToolResult]:
        """Execute all tools; parallelizes only when all tools are safe."""
        return await self.execute_many(
            [{"name": tool.name, "tool_input": {}} for tool in self.tools]
        )

    def get_tool(self, name: str) -> BaseTool:
        return self.tool_map.get(name)

    def add_tool(self, tool: BaseTool):
        """Add a single tool to the collection.

        If a tool with the same name already exists, it will be skipped and a warning will be logged.
        """
        if tool.name in self.tool_map:
            logger.warning(f"Tool {tool.name} already exists in collection, skipping")
            return self

        self.tools += (tool,)
        self.tool_map[tool.name] = tool
        self._invalidate_params_cache()
        return self

    def add_tools(self, *tools: BaseTool):
        """Add multiple tools to the collection.

        If any tool has a name conflict with an existing tool, it will be skipped and a warning will be logged.
        """
        for tool in tools:
            self.add_tool(tool)
        return self

    def reset_stats(self) -> None:
        self._stats.update(
            {
                "execute_calls": 0,
                "execute_errors": 0,
                "batch_calls": 0,
                "batch_parallel_calls": 0,
                "params_cache_hits": 0,
                "params_cache_misses": 0,
                "total_execute_latency_ms": 0.0,
            }
        )

    def get_stats(self) -> Dict[str, Any]:
        snapshot = dict(self._stats)
        execute_calls = int(snapshot.get("execute_calls", 0))
        snapshot["avg_execute_latency_ms"] = (
            float(snapshot.get("total_execute_latency_ms", 0.0)) / execute_calls
            if execute_calls > 0
            else 0.0
        )
        snapshot["parallel_execution_enabled"] = bool(self.parallel_execution_enabled)
        snapshot["parallel_max_workers"] = int(self.parallel_max_workers)
        return snapshot
