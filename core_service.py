"""
AICoreService — 异步 AI 核心服务层

取代原 main.py 中的 AIWorker 线程，使用 asyncio 编排所有 AI 相关业务逻辑：
  LLM 调用、记忆检索/存储、Agent 任务执行、TTS 请求。

通过回调（callback）/ PyQt 信号与 GUI 层解耦。

依赖:
  - modules.llm.call_llm          (同步 → asyncio.to_thread)
  - modules.memory.MemoryManager   (同步 → asyncio.to_thread)
  - modules.agent.core.ManusAgent  (内部已有 async 循环，包装为协程)
  - modules.voice.VoiceManager     (同步 → asyncio.to_thread)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from modules.avatar.expression import Emotion
from modules.config import AppConfig
from modules.json_utils import extract_first_json
from modules.llm import call_llm
from modules.logging_config import get_logger
from modules.utils import clean_text, filter_emotion_tags

logger = get_logger("AICoreService")


# ---- 事件回调协议 ----


@dataclass
class ServiceCallbacks:
    """GUI 层注册的回调集合，由 AICoreService 在适当时机调用。

    所有回调都在 asyncio 事件循环所在的线程中被调用，
    如果回调需要操作 GUI，应当通过 Qt 信号代理到主线程。
    """

    on_response_ready: Optional[Callable[[str], None]] = None
    on_expression_change: Optional[Callable[[object], None]] = None
    on_status_update: Optional[Callable[[str], None]] = None
    on_speak_request: Optional[Callable[[str], None]] = None
    on_shutdown: Optional[Callable[[], None]] = None


class AICoreService:
    """异步 AI 核心服务 — 替代原 AIWorker 线程。

    使用方式:
        service = AICoreService(config, memory_manager, voice_manager, agent, callbacks)
        # 在 asyncio 事件循环中启动
        asyncio.ensure_future(service.start())
        # 提交用户输入
        service.submit("你好")
        # 关闭
        await service.stop()
    """

    def __init__(
        self,
        config: AppConfig,
        memory_manager,
        voice_manager,
        agent=None,
        callbacks: Optional[ServiceCallbacks] = None,
    ):
        self.config = config
        self.memory_manager = memory_manager
        self.voice_manager = voice_manager
        self.agent = agent
        self.cb = callbacks or ServiceCallbacks()

        # 异步输入队列（替代 queue.Queue）
        self._input_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 强制继续标记
        self._force_continue_next = False

    # ==================== 生命周期 ====================

    async def start(self):
        """启动主处理循环（作为 asyncio Task 运行）。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.current_task() or asyncio.ensure_future(self._main_loop())
        if asyncio.current_task() is not None:
            await self._main_loop()
        logger.info("AICoreService 已启动")

    def start_background(self):
        """在当前事件循环中以后台 Task 启动，不阻塞调用者。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._main_loop())
        logger.info("AICoreService 后台 Task 已创建")

    async def stop(self):
        """优雅停止服务。"""
        self._running = False
        # 放入 sentinel 以唤醒阻塞的 get()
        await self._input_queue.put(None)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AICoreService 已停止")

    def submit(self, text: str):
        """线程安全地提交用户输入。

        可以从任意线程调用（例如控制台输入线程或 GUI 线程）。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            self._input_queue.put_nowait(text)
        else:
            # 从非 asyncio 线程提交
            asyncio.run_coroutine_threadsafe(self._input_queue.put(text), self._get_loop())

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """获取关联的事件循环。"""
        if self._task is not None:
            return self._task.get_loop()
        return asyncio.get_event_loop()

    # ==================== 主循环 ====================

    async def _main_loop(self):
        """核心事件循环 — 逐条处理用户输入。"""
        while self._running:
            try:
                user_input = await asyncio.wait_for(self._input_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if user_input is None:
                break

            try:
                await self._process_input(user_input)
            except Exception as e:
                logger.error(f"处理输入异常: {e}", exc_info=True)

        logger.info("AICoreService 主循环退出")

    # ==================== 输入处理 ====================

    async def _process_input(self, user_input: str):
        """处理单条用户输入 — 原 AIWorker.run() 中的核心逻辑。"""
        # 退出命令
        if user_input.lower() in ("exit", "quit"):
            self._emit("on_shutdown")
            return

        # 状态查询
        if user_input.lower() == "status":
            stats = await asyncio.to_thread(self.memory_manager.get_memory_stats)
            status_msg = (
                f"📊 记忆系统状态:\n"
                f"  ├─ 对话轮次: {stats['short_term']}/{stats['short_term_capacity']} 轮\n"
                f"  ├─ 短期交互: {stats['working_memory']} 条\n"
                f"  ├─ 长期记忆: {stats['long_term']} 条\n"
                f"  └─ 概念节点: {stats.get('concept_nodes', 0)} 个"
            )
            self._emit("on_status_update", status_msg)
            return

        cleaned_input = clean_text(user_input)
        if not cleaned_input.strip():
            return

        # ---- 教学模式触发 ----
        if re.search(r"(?:开始教学|我要教你|我(?:来)?教你|来教你)", cleaned_input):
            await self._handle_learning_start(cleaned_input)
            return

        if any(kw in cleaned_input for kw in ("教学结束", "学会了吗")):
            await self._handle_learning_stop()
            return

        # 存入短期记忆
        await asyncio.to_thread(self.memory_manager.add_to_short_term, "用户", cleaned_input)

        # 检索相关记忆
        memory_context = await asyncio.to_thread(self.memory_manager.retrieve_memories, cleaned_input)
        if memory_context == "无相关记忆。":
            memory_context = ""

        # 思考表情
        self._emit("on_expression_change", Emotion.THINKING)

        # 强制继续
        if self._force_continue_next and cleaned_input.lower() not in ("status", "exit", "quit"):
            cleaned_input = "请继续执行未完成的任务，发送指令标签。\n\n" + cleaned_input
            self._force_continue_next = False

        full_memory_context = memory_context

        # ---- 调用 LLM ----
        system_prompt = self.config.system_prompt or ""
        model_name = self.config.model_name or ""
        ai_response = await asyncio.to_thread(call_llm, system_prompt, model_name, cleaned_input, full_memory_context)

        skip_tts = False

        # ---- 检测 [SUMMON_AGENT] 标签 ----
        handled = await self._try_handle_summon_agent(ai_response, cleaned_input, system_prompt, model_name)
        if handled:
            return

        # ---- 自动检测 LLM 直接输出工具调用 JSON ----
        handled = await self._try_handle_tool_json(ai_response, cleaned_input, system_prompt, model_name)
        if handled:
            skip_tts = True
            ai_response = handled  # agent 结果替换原响应

        # 常规响应
        self._emit("on_expression_change", ai_response)
        self._emit("on_response_ready", ai_response)

        # 记忆
        if ai_response != "抱歉，我现在有点卡住了。":
            await asyncio.to_thread(self.memory_manager.add_to_short_term, "AI", ai_response)
            await asyncio.to_thread(
                self.memory_manager.store_memory, f"用户: {cleaned_input}\nAI: {ai_response}"
            )

        # 语音
        if not skip_tts:
            self._emit("on_speak_request", ai_response)

    # ==================== Agent 相关 ====================

    async def _try_handle_summon_agent(
        self, ai_response: str, cleaned_input: str, system_prompt: str, model_name: str
    ) -> bool:
        """检测并处理 [SUMMON_AGENT] 标签，返回 True 如果已处理。"""
        summon_pattern = r"\[SUMMON_AGENT\](.*?)\[/SUMMON_AGENT\]"
        m = re.search(summon_pattern, ai_response, re.DOTALL)
        if not m and "[SUMMON_AGENT]" in ai_response:
            lenient_pattern = r"\[SUMMON_AGENT\]\s*(?:```\w*\s*)?(\{.*?\})\s*(?:```)?"
            m = re.search(lenient_pattern, ai_response, re.DOTALL)
        if not m:
            return False

        pre_text = ai_response[: m.start()].strip()
        tag_json = m.group(1).strip()
        tag_json = re.sub(r"^```\w*\s*", "", tag_json)
        tag_json = re.sub(r"\s*```\s*$", "", tag_json)
        tag_json = tag_json.strip()

        task_desc = self._parse_task_desc(tag_json, cleaned_input)

        # 先播放闲聊文本
        if pre_text:
            self._emit("on_speak_request", pre_text)
        else:
            start_reply = await self._generate_short_reply(
                system_prompt, model_name,
                "用户让你帮忙执行一个操作任务。请用你的人设风格，只生成一句简短的确认语（5-10字），"
                "表示你开始执行了。只输出确认语，不要输出任何其他内容。",
                fallback="好的~",
            )
            self._emit("on_speak_request", start_reply)

        # 执行 Agent 任务
        agent_result = await self._run_agent_task(task_desc)

        clean_pre = pre_text or ""
        combined = (clean_pre + "\n\n[Agent 执行结果]\n" + agent_result).strip()

        self._emit("on_expression_change", combined)
        self._emit("on_response_ready", combined)

        if combined != "抱歉，我现在有点卡住了。":
            await asyncio.to_thread(self.memory_manager.add_to_short_term, "AI", combined)
            await asyncio.to_thread(
                self.memory_manager.store_memory, f"用户: {cleaned_input}\nAI: {combined}"
            )

        # 完成后语音
        await self._speak_agent_completion(agent_result, system_prompt, model_name)
        return True

    async def _try_handle_tool_json(
        self, ai_response: str, cleaned_input: str, system_prompt: str, model_name: str
    ) -> Optional[str]:
        """检测 LLM 直接输出工具调用 JSON，返回 agent_result 或 None。"""
        try:
            parsed_agent = extract_first_json(ai_response)
            if not (parsed_agent and isinstance(parsed_agent, dict) and "tool" in parsed_agent):
                return None
        except Exception:
            return None

        logger.info("检测到 LLM 直接输出工具调用 JSON，转交 Agent 处理")
        if not self.agent:
            logger.warning("Agent 未初始化，无法处理工具调用")
            return None

        agent_result = await self._run_agent_task(cleaned_input)
        await self._speak_agent_completion(agent_result, system_prompt, model_name)
        return agent_result

    async def _run_agent_task(self, task_desc: str) -> str:
        """执行 Agent 任务（异步）。"""
        if not self.agent or not task_desc:
            return "⚠️ Agent 未启用" if not self.agent else "⚠️ 无任务描述"

        logger.info(f"Invoking ManusAgent.run_task — task_desc={task_desc}")
        try:
            result = await asyncio.to_thread(self.agent.run_task, task_desc)
            logger.info(
                f"ManusAgent.run_task completed — result(len)="
                f"{len(result) if isinstance(result, str) else 'N/A'}"
            )
            return result
        except Exception as e:
            logger.exception(f"ManusAgent.run_task raised exception: {e}")
            return f"❌ Agent 执行异常: {e}"

    async def _speak_agent_completion(self, agent_result: str, system_prompt: str, model_name: str):
        """根据 Agent 执行结果生成语音回复。"""
        is_success = any(kw in agent_result.lower() for kw in ("success", "完成", "成功"))
        is_failure = any(kw in agent_result.lower() for kw in ("failure", "失败", "异常", "错误"))

        if is_success:
            prompt = (
                "你刚刚帮用户完成了一个操作任务，任务成功了。请用你的人设风格，"
                "生成一句简短的完成确认语（5-15字）。只输出确认语。"
            )
            fallback = "搞定啦~"
        elif is_failure:
            prompt = (
                "你刚刚帮用户执行一个操作任务，但是遇到了一些问题。请用你的人设风格，"
                "生成一句简短的抱歉语（5-15字）。只输出抱歉语。"
            )
            fallback = "抱歉没成功呢..."
        else:
            prompt = (
                "你刚刚帮用户处理了一个操作任务。请用你的人设风格，"
                "生成一句简短的完成确认语（5-15字）。只输出确认语。"
            )
            fallback = "处理好了~"

        voice_reply = await self._generate_short_reply(system_prompt, model_name, prompt, fallback)
        self._emit("on_speak_request", voice_reply)

    # ==================== 教学模式 ====================

    async def _handle_learning_start(self, cleaned_input: str):
        m = re.search(r"(?:开始教学|我要教你|我(?:来)?教你|来教你)(.*)", cleaned_input)
        task_name = m.group(1).strip() if m else ""
        if self.agent:
            await asyncio.to_thread(self.agent.start_learning, task_name)
            msg = "好的，进入教学模式，请演示一遍给我看。"
        else:
            msg = "⚠️ Agent 未初始化，无法进入教学模式。"
        self._emit("on_speak_request", msg)
        self._emit("on_response_ready", msg)

    async def _handle_learning_stop(self):
        if self.agent:
            result = await asyncio.to_thread(self.agent.stop_learning)
        else:
            result = "⚠️ Agent 未初始化，无法结束教学。"
        self._emit("on_speak_request", result)
        self._emit("on_response_ready", result)

    # ==================== 工具方法 ====================

    def _parse_task_desc(self, tag_json: str, cleaned_input: str) -> str:
        """从 SUMMON_AGENT JSON 中提取任务描述。"""
        try:
            payload = json.loads(tag_json)
            task_desc = payload.get("task")
            if not task_desc:
                task_desc = cleaned_input
                logger.info(
                    f"SUMMON_AGENT JSON 无 task 字段(keys={list(payload.keys())})，"
                    f"使用用户原始输入作为任务: {task_desc}"
                )
            elif isinstance(task_desc, str) and len(task_desc) < 20 and re.match(r"^[a-zA-Z0-9_]+$", task_desc):
                logger.warning(
                    f"SUMMON_AGENT JSON 中的 task 看起来是工具名称 '{task_desc}'，"
                    f"不是完整查询。使用用户原始输入: {cleaned_input}"
                )
                task_desc = cleaned_input
        except Exception as e:
            logger.warning(f"解析 SUMMON_AGENT JSON 失败: {e}，使用用户输入作为 task")
            task_desc = cleaned_input
        return task_desc

    async def _generate_short_reply(
        self, system_prompt: str, model_name: str, prompt: str, fallback: str = "好的~"
    ) -> str:
        """通过 LLM 生成简短回复，失败时返回 fallback。"""
        try:
            reply = await asyncio.to_thread(call_llm, system_prompt, model_name, prompt, "")
            reply = reply.strip().strip("\"'")
            if reply and len(reply) < 50:
                return reply
        except Exception as e:
            logger.warning(f"生成简短回复失败: {e}")
        return fallback

    def _emit(self, callback_name: str, *args):
        """安全地调用回调。"""
        fn = getattr(self.cb, callback_name, None)
        if fn:
            try:
                fn(*args)
            except Exception as e:
                logger.error(f"回调 {callback_name} 异常: {e}", exc_info=True)
