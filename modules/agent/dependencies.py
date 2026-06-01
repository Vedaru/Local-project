"""Agent / OpenManus 运行时依赖清单（供自检与 agent_service 共用）。"""

from __future__ import annotations

from dataclasses import dataclass

import importlib.util


@dataclass(frozen=True)
class AgentDependencySpec:
    """单个 Python 依赖项。"""

    module_name: str
    pip_spec: str
    critical: bool = True
    description: str = ""


# critical=True：缺失则 Manus / WebSearch 无法正常工作
AGENT_RUNTIME_DEPENDENCIES: tuple[AgentDependencySpec, ...] = (
    AgentDependencySpec("mcp", "mcp>=1.0.0", True, "OpenManus MCP 工具"),
    AgentDependencySpec("duckduckgo_search", "duckduckgo_search==3.9.6", True, "WebSearch DuckDuckGo"),
    AgentDependencySpec("baidusearch", "baidusearch==1.0.3", False, "WebSearch 百度（可选）"),
    AgentDependencySpec("browser_use", "browser-use==0.1.40", False, "浏览器自动化（可选）"),
    AgentDependencySpec("playwright", "playwright==1.40.0", False, "Playwright 内核（可选）"),
    AgentDependencySpec("tenacity", "tenacity==8.2.3", True, "WebSearch 重试"),
    AgentDependencySpec("loguru", "loguru==0.7.2", True, "OpenManus 日志"),
)


def is_module_importable(module_name: str) -> bool:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
    if spec is None:
        return False
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def missing_agent_dependencies(
    *,
    include_optional: bool = False,
) -> list[AgentDependencySpec]:
    missing: list[AgentDependencySpec] = []
    for spec in AGENT_RUNTIME_DEPENDENCIES:
        if not include_optional and not spec.critical:
            continue
        if not is_module_importable(spec.module_name):
            missing.append(spec)
    return missing


def pip_install_specs(specs: list[AgentDependencySpec]) -> tuple[bool, str]:
    """尝试安装缺失依赖；返回 (成功, 日志摘要)。"""
    if not specs:
        return True, ""
    import subprocess
    import sys

    packages = [s.pip_spec for s in specs]
    cmd = [sys.executable, "-m", "pip", "install", "-q", *packages]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err[:500]
    return True, " ".join(packages)


def verify_manus_importable() -> tuple[bool, str]:
    """在 Agent 与 OpenManus 相同的路径下验证 Manus 可导入。"""
    import os
    import sys

    openmanus_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "openmanus")
    )
    inserted = False
    if openmanus_root not in sys.path:
        sys.path.insert(0, openmanus_root)
        inserted = True
    try:
        from app.agent.manus import Manus  # noqa: F401

        _ = Manus
        return True, "Manus 导入成功"
    except Exception as exc:
        return False, str(exc)
    finally:
        if inserted and sys.path and sys.path[0] == openmanus_root:
            sys.path.pop(0)
