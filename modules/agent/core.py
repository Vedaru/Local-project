"""
ManusAgent — 基于 OpenManus 框架的智能体同步包装

将 OpenManus 的异步 Manus agent 封装为同步的 run_task() 接口，
以便与现有的 PyQt6 主循环和 AIWorker 线程无缝集成。

架构：
  调用者 (sync)  →  ManusAgent.run_task()
                      └→  asyncio event loop (在独立线程中运行)
                            └→  OpenManus Manus agent (async)
                                  └→  ToolCallAgent.think() / act()
                                        └→  BrowserUseTool, PythonExecute, WebSearch, ...

LLM 配置统一：
  OpenManus 的 config.toml 由本模块在首次导入 OpenManus 前自动生成，
  API 设置(model, base_url, api_key)全部从项目的 .env / modules.config 中读取，
  保证单一配置源，无需手动编辑 config.toml。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import os
import sys
import threading
from typing import Callable, Optional

from ..logging_config import get_logger
from ..task_completion import TaskCompletionHelper

logger = get_logger("ManusAgent")

# 全局 speak 回调，用于在 agent 执行时输出语音
_global_speak_callback: Optional[Callable[[str], None]] = None


class AgentTaskCancelledError(RuntimeError):
    """Raised when an in-flight agent task is cancelled by user request."""


def set_agent_speak_callback(callback: Optional[Callable[[str], None]]) -> None:
    """设置全局 speak 回调函数，用于 agent 执行时的语音输出。

    Parameters
    ----------
    callback : Optional[Callable[[str], None]]
        语音回调函数，接收要说的文本。设为 None 禁用 speak。
    """
    global _global_speak_callback
    _global_speak_callback = callback
    if callback:
        logger.info("Agent speak 回调已设置")
    else:
        logger.info("Agent speak 回调已禁用")


def _agent_speak(text: str) -> None:
    """在 agent 执行时调用此函数以输出语音。

    Parameters
    ----------
    text : str
        要说的文本。
    """
    global _global_speak_callback
    if _global_speak_callback and text and text.strip():
        try:
            _global_speak_callback(text.strip())
        except Exception as e:
            logger.error(f"Agent speak 回调异常: {e}")


# 在module导入时创建一个自定义的Manus类，支持speak功能
_speaking_manus_class = None


def _create_speaking_manus_class():
    """动态创建一个支持speak的Manus agent类。"""
    global _speaking_manus_class
    if _speaking_manus_class is not None:
        return _speaking_manus_class

    try:
        from app.agent.manus import Manus

        class SpeakingManus(Manus):
            """支持语音输出的 Manus agent。

            在think和act中添加语音描述，让用户能听到agent的思考过程和操作步骤。
            """

            async def think(self) -> bool:
                """执行think步骤，并输出思考过程的语音描述。"""
                result = bool(await super().think())

                # 在think后输出思考内容和选择的工具
                if result and self.tool_calls and len(self.tool_calls) > 0:
                    tool_names = [call.function.name for call in self.tool_calls]
                    if len(tool_names) == 1:
                        speak_text = f"我现在需要使用工具: {tool_names[0]}"
                    else:
                        tools_str = "、".join(tool_names)
                        speak_text = f"我现在需要依次使用以下工具: {tools_str}"
                    _agent_speak(speak_text)

                return result

            async def act(self) -> str:
                """执行act步骤，并输出执行内容的语音描述。"""
                if self.tool_calls:
                    # 在执行前输出即将执行的工具
                    for i, call in enumerate(self.tool_calls):
                        tool_name = call.function.name
                        if len(self.tool_calls) > 1:
                            speak_text = f"执行第 {i+1} 个工具: {tool_name}"
                        else:
                            speak_text = f"正在执行工具: {tool_name}"
                        _agent_speak(speak_text)

                result = str(await super().act())

                # 执行完成后输出完成信息
                if self.tool_calls:
                    _agent_speak("工具执行已完成，分析结果中")

                return result

        _speaking_manus_class = SpeakingManus
        return _speaking_manus_class
    except Exception as e:
        logger.warning(f"创建 SpeakingManus 类失败: {e}，回退到普通 Manus")
        return None


# ---- 确保 OpenManus 在 Python path 中 ----
_OPENMANUS_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "openmanus"))
if _OPENMANUS_ROOT not in sys.path:
    sys.path.insert(0, _OPENMANUS_ROOT)

# ---- 标记：config.toml 是否已同步 ----
_config_synced = False
_config_sync_lock = threading.Lock()


def _sync_openmanus_config():
    """将项目的 LLM API 设置同步写入 OpenManus 的 config.toml。

    核心思路：项目的 .env 是唯一配置源，OpenManus 的 config.toml 只是它的
    派生文件，每次 ManusAgent 初始化时自动重新生成，开发者无需手动维护。

    读取来源：
      - ARK_API_KEY       → .env（通过 os.environ，已由 modules.config 的 load_dotenv 加载）
      - ARK_BASE_URL      → .env（可选，默认 https://ark.cn-beijing.volces.com/api/v3）
      - MODEL_NAME        → .env / modules.config.MODEL_NAME
    """
    global _config_synced
    if _config_synced:
        return

    with _config_sync_lock:
        if _config_synced:
            return

        from ..config import MODEL_NAME

        api_key = os.environ.get("ARK_API_KEY", "")
        base_url = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        model = MODEL_NAME or "deepseek-v3-250324"

        config_dir = os.path.join(_OPENMANUS_ROOT, "config")
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "config.toml")

        toml_content = f"""\
# ╔══════════════════════════════════════════════════════════════╗
# ║  Auto-generated by modules/agent/core.py — 请勿手动编辑     ║
# ║  修改 API 设置请编辑项目根目录的 .env 文件                    ║
# ╚══════════════════════════════════════════════════════════════╝

[llm]
model = "{model}"
base_url = "{base_url}"
api_key = "{api_key}"
max_tokens = 8192
temperature = 0.0
api_type = ""
api_version = ""

[search]
engine = "Baidu"
fallback_engines = ["DuckDuckGo", "Bing"]
lang = "zh"
country = "cn"

[browser]
headless = false
disable_security = true

[mcp]
server_reference = "app.mcp.server"
"""

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(toml_content)
            _config_synced = True
            logger.info(f"OpenManus config.toml 已同步 (model={model}, base_url={base_url})")
        except Exception as e:
            logger.error(f"写入 OpenManus config.toml 失败: {e}")
            raise


class ManusAgent:
    """OpenManus Manus agent 的同步包装。

    对外暴露 ``run_task(task_description) -> str`` 接口，
    内部通过独立的 asyncio 事件循环运行 OpenManus 的异步 Manus agent。

    LLM 设置自动从项目 .env 中读取，无需额外配置。

    Parameters
    ----------
    system_prompt : str, optional
        附加的 system prompt（会注入到 Manus agent 中）。
    max_steps : int
        最大执行步骤数，默认 100。
    speak_callback : Optional[Callable[[str], None]]
        语音回调函数，用于在 agent 执行时输出语音描述。
    """

    def __init__(
        self,
        system_prompt: str = "",
        max_steps: int = 100,
        task_timeout_seconds: float = 300.0,
        speak_callback: Optional[Callable[[str], None]] = None,
    ):
        self.system_prompt = system_prompt or ""
        self.max_steps = max_steps
        self.task_timeout_seconds = max(0.0, float(task_timeout_seconds))
        self.speak_callback = speak_callback

        # 设置全局 speak 回调
        if speak_callback:
            set_agent_speak_callback(speak_callback)

        self._agent = None  # 延迟创建（在 async 上下文中初始化）
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._run_lock = threading.Lock()
        self._active_future_lock = threading.Lock()
        self._active_future: Optional[concurrent.futures.Future] = None
        self._initialized = False

        # 在任何 OpenManus 模块被导入之前，先将项目 API 设置同步到 config.toml
        _sync_openmanus_config()

        logger.info(
            "ManusAgent 初始化 (OpenManus 后端, " f"max_steps={self.max_steps}, timeout={self.task_timeout_seconds}s)"
        )

        # 启动后台事件循环线程
        self._start_event_loop()

    def _start_event_loop(self):
        """启动一个持久的后台 asyncio 事件循环线程。"""
        ready = threading.Event()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True)
        self._loop_thread.start()
        if not ready.wait(timeout=5):
            raise RuntimeError("后台 asyncio 事件循环启动超时")
        if self._loop is None:
            raise RuntimeError("后台 asyncio 事件循环启动失败")
        logger.debug("后台 asyncio 事件循环已启动")

    def _run_coro(self, coro, timeout: Optional[float] = None):
        """在后台事件循环中运行协程并同步等待结果。"""
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError("后台事件循环未启动或已关闭")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        with self._active_future_lock:
            self._active_future = future
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            future.cancel()
            timeout_label = timeout if timeout is not None else self.task_timeout_seconds
            raise TimeoutError(f"Agent 执行超时（>{timeout_label}s）") from e
        except concurrent.futures.CancelledError as e:
            raise AgentTaskCancelledError("Agent 任务已取消") from e
        finally:
            with self._active_future_lock:
                if self._active_future is future:
                    self._active_future = None

    def request_cancel(self) -> bool:
        """请求取消当前正在执行的任务。"""
        with self._active_future_lock:
            future = self._active_future

        if future is None or future.done():
            return False

        cancelled = future.cancel()
        if cancelled:
            logger.info("ManusAgent 收到取消请求，已尝试取消当前任务")
        return cancelled

    async def _ensure_agent(self):
        """确保 OpenManus Manus agent 已创建（延迟初始化）。"""
        if self._agent is not None:
            return

        # 延迟导入 — config.toml 此时已由 __init__ 中的 _sync_openmanus_config() 写好
        from app.config import config

        allowed_directories = "\n".join(
            f"- {path}" for path in config.workspace_roots
        )

        # 构建自定义的 system prompt
        base_prompt = (
            "你是一个强大的 AI 智能体，能够解决用户提出的各种任务。你拥有多种工具可以调用，"
            "包括浏览器自动化、Python 代码执行、文件编辑、网页搜索等。"
            "你还拥有 memory_md 工具，可将稳定偏好、项目约定和过程性笔记写入 Markdown 记忆文件。"
            "\n\n【执行风格】"
            "请用中文回答和思考。"
            "为了让用户了解你的进行，请在每个思考步骤中使用 JSON 格式的思考内容，例如："
            '{"thought": "我现在需要使用搜索工具来查找相关信息", "next_step": "search"}'
            "\n\n【文件操作规范】"
            "严禁将纯文本内容直接写入 .pptx/.docx/.xlsx/.pdf 这类二进制格式文件。"
            "若用户要求生成 PPTX/DOCX/PDF，优先使用 document_skill 工具；"
            "仅在需要非常定制的底层逻辑时，再使用 python_execute。"
            "当任务是制作或美化 PPT/Word/PDF 时，默认采用两阶段流程："
            "第一阶段在本地目录先生成样式草案（优先 CSS 文件，如 theme.css）；"
            "第二阶段通过 document_skill 将样式映射到目标格式对象样式并导出文件。"
            "若转换失败，先保留 CSS 与中间产物，再调整映射规则重试，不要直接写二进制文本。"
            f"\n\n【工作目录】"
            f"主工作目录: {config.workspace_root}"
            f"\n本地可访问目录:\n{allowed_directories}"
            "\n以上目录仅用于 Local 端文件处理，不影响 IDE 工作区。"
        )
        if self.system_prompt:
            base_prompt = self.system_prompt + "\n\n" + base_prompt

        # 尝试使用 SpeakingManus（支持语音描述）；如果失败则回落到普通 Manus
        agent_class = _create_speaking_manus_class()
        if agent_class is None:
            from app.agent.manus import Manus
            agent_class = Manus

        self._agent = await agent_class.create(
            system_prompt=base_prompt,
            max_steps=self.max_steps,
        )
        self._initialized = True
        logger.info("OpenManus Manus agent 创建成功")

    def run_task(self, task_description: str) -> str:
        """执行给定任务（同步、阻塞）并返回最终结果字符串。

        Parameters
        ----------
        task_description : str
            任务描述文本。

        Returns
        -------
        str
            Agent 执行结果的文本摘要。
        """
        task_description = (task_description or "").strip()
        if not task_description:
            return "⚠️ 无任务描述"

        logger.info(f"ManusAgent.run_task — task={task_description[:200]}")

        try:
            with self._run_lock:
                result = self._run_coro(self._async_run_task(task_description), timeout=self.task_timeout_seconds)
            normalized = self._normalize_result(result)
            self._persist_session_memory_note(task_description, normalized)
            logger.info("ManusAgent.run_task 完成 — result(len)=" f"{len(normalized)}")
            return normalized
        except TimeoutError as e:
            logger.error(f"ManusAgent.run_task 超时: {e}")
            timeout_msg = f"⏱️ Agent 执行超时，请简化任务后重试（{self.task_timeout_seconds:.0f}s）"
            self._persist_session_memory_note(task_description, timeout_msg)
            return timeout_msg
        except AgentTaskCancelledError:
            canceled_msg = "⚠️ Agent 任务已被用户中止"
            self._persist_session_memory_note(task_description, canceled_msg)
            logger.info("ManusAgent.run_task 被取消")
            return canceled_msg
        except Exception as e:
            logger.exception(f"ManusAgent.run_task 异常: {e}")
            error_msg = f"❌ Agent 执行异常: {e}"
            self._persist_session_memory_note(task_description, error_msg)
            return error_msg

    def _persist_session_memory_note(self, task_description: str, result: str) -> None:
        """Best-effort persistence of task/result to session markdown memory."""
        if not self._initialized:
            return

        try:
            self._run_coro(self._async_persist_session_memory_note(task_description, result), timeout=10)
        except Exception as e:
            logger.debug(f"写入 memory_md 会话笔记失败: {e}")

    async def _async_persist_session_memory_note(self, task_description: str, result: str) -> None:
        """Append task execution trace into session/task_runs.md via memory_md tool."""
        from app.tool.memory_md import MemoryMarkdownTool

        tool = MemoryMarkdownTool()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_task = (task_description or "").strip() or "(empty task)"
        safe_result = (result or "").strip() or "(empty result)"
        entry = (
            f"\n## {timestamp}\n"
            f"### task\n{safe_task}\n\n"
            "### result\n"
            f"```\n{safe_result}\n```\n"
        )
        await tool.execute(
            command="append",
            scope="session",
            file="task_runs.md",
            content=entry,
        )

    async def _persist_session_memory_note_async(self, task_description: str, result: str) -> None:
        """Best-effort async persistence of task/result into session markdown memory."""
        if not self._initialized:
            return
        try:
            await self._async_persist_session_memory_note(task_description, result)
        except Exception as e:
            logger.debug(f"异步写入 memory_md 会话笔记失败: {e}")

    def _preprocess_task(self, task_description: str) -> str:
        """Normalize and enrich raw task description before execution."""
        return self._prepare_task_description(task_description)

    async def _execute_steps(self, prepared_task: str) -> object:
        """Execute agent steps on prepared task and return raw output."""
        from app.schema import AgentState

        if self._agent is None:
            raise RuntimeError("OpenManus agent 初始化失败")

        self._agent.state = AgentState.IDLE
        self._agent.current_step = 0
        self._agent.memory.clear()
        return await self._agent.run(prepared_task)

    def _postprocess_result(self, result: object) -> str:
        """Normalize raw agent output for external callers."""
        return self._normalize_result(result)

    async def _async_run_task(self, task_description: str) -> str:
        """异步执行任务（在后台事件循环线程中运行）。"""
        await self._ensure_agent()
        prepared_task = self._preprocess_task(task_description)

        try:
            raw_result = await self._execute_steps(prepared_task)
            return self._postprocess_result(raw_result)
        except Exception as e:
            logger.exception(f"OpenManus agent 执行失败: {e}")
            return f"❌ Agent 内部错误: {e}"

    def _prepare_task_description(self, task_description: str) -> str:
        """
        Prepare task description by adding completion understanding guidance.

        NOTE: Does NOT use keyword matching or task classification.
        Instead, provides process-based reasoning guidance for the agent to
        understand when to stop based on goal achievement.
        """
        result = task_description

        # Add general process-based completion guidance
        # This applies equally to ALL task types
        result += str(TaskCompletionHelper.get_completion_guidance())

        # Add process awareness guidance (not keyword-triggered)
        result += str(TaskCompletionHelper.get_process_awareness_guidance())

        return result

    @staticmethod
    def _normalize_result(result) -> str:
        """标准化 Agent 返回值，避免上层收到空结果或非字符串。"""
        if result is None:
            return "⚠️ Agent 未返回有效结果"

        if not isinstance(result, str):
            result = str(result)

        result = result.strip()
        return result or "⚠️ Agent 未返回有效结果"

    def cleanup(self):
        """清理资源。"""
        try:
            if self._agent is not None:
                self._run_coro(self._agent.cleanup(), timeout=10)
                self._agent = None
        except TimeoutError:
            logger.warning("Agent cleanup 超时，继续执行后续清理")
        except Exception as e:
            logger.warning(f"Agent cleanup 异常: {e}")

        # 停止事件循环
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread:
            self._loop_thread.join(timeout=3)
        logger.info("ManusAgent 资源已清理")

    # ======= 向后兼容的学习接口（空实现）=======
    def start_learning(self, task_name: str) -> str:
        """教学模式（当前 OpenManus 后端暂不支持）。"""
        logger.info(f"start_learning called (task={task_name}) — OpenManus 后端暂不支持教学模式")
        return "⚠️ 当前 Agent 后端 (OpenManus) 暂不支持教学模式。"

    def stop_learning(self) -> str:
        """结束教学模式（空实现）。"""
        return "⚠️ 当前 Agent 后端 (OpenManus) 暂不支持教学模式。"

    # ======= 异步接口 =======

    async def run_task_async(self, task_description: str) -> str:
        """异步执行任务，避免通过线程包装同步接口。"""
        task_description = (task_description or "").strip()
        if not task_description:
            return "⚠️ 无任务描述"

        logger.info(f"ManusAgent.run_task_async — task={task_description[:200]}")
        acquired = self._run_lock.acquire(blocking=False)
        if not acquired:
            return "⚠️ Agent 正在执行其他任务，请稍后再试"

        try:
            raw_result = await asyncio.wait_for(
                self._async_run_task(task_description),
                timeout=self.task_timeout_seconds,
            )
            normalized = self._normalize_result(raw_result)
            await self._persist_session_memory_note_async(task_description, normalized)
            logger.info("ManusAgent.run_task_async 完成 — result(len)=" f"{len(normalized)}")
            return normalized
        except asyncio.TimeoutError:
            timeout_msg = f"⏱️ Agent 执行超时，请简化任务后重试（{self.task_timeout_seconds:.0f}s）"
            await self._persist_session_memory_note_async(task_description, timeout_msg)
            logger.error(f"ManusAgent.run_task_async 超时（>{self.task_timeout_seconds:.0f}s）")
            return timeout_msg
        except AgentTaskCancelledError:
            canceled_msg = "⚠️ Agent 任务已被用户中止"
            await self._persist_session_memory_note_async(task_description, canceled_msg)
            logger.info("ManusAgent.run_task_async 被取消")
            return canceled_msg
        except Exception as e:
            error_msg = f"❌ Agent 执行异常: {e}"
            await self._persist_session_memory_note_async(task_description, error_msg)
            logger.exception(f"ManusAgent.run_task_async 异常: {e}")
            return error_msg
        finally:
            self._run_lock.release()
