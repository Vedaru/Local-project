"""
LLM 模块 - OpenAI 接口
支持人类化记忆系统的上下文注入

优化点：
- 缓存拼装好的 system prompt，避免每次调用都重复拼接
- max_tokens 从 200 提升到 800（200 对 Agent JSON 输出远远不够）
- 指数退避首次间隔从 1.5s 降到 1.0s
"""

import threading
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from .config import client
from .json_utils import extract_first_json
from .logging_config import get_logger

logger = get_logger("llm")


@dataclass(frozen=True)
class AgentRoutingDecision:
    """Semantic routing decision for whether a user turn should invoke Agent."""

    should_trigger: bool = False
    confidence: float = 0.0
    task: str = ""
    reason: str = ""

# ---- 缓存已拼装的 system prompt ----
_prompt_cache_lock = threading.Lock()
_prompt_cache: dict[int, str] = {}  # key: 原始 system_prompt 的 hash -> 拼装后的完整 prompt


def _build_enhanced_prompt(base_prompt: str) -> str:
    """在基础 system prompt 上追加 Agent 触发提示（OpenManus 会自行管理工具描述）。"""
    parts = [base_prompt]

    parts.append(
        "\n\n【对话输出规范（硬约束）】\n"
        "你的回复必须像真人口语，直接可说出口。\n"
        "禁止输出舞台说明、动作描写、心理旁白或镜头叙述。\n"
        "禁止出现类似“拍了拍脑袋”“小声嘀咕”“突然想到什么似的”这类小说化表达。\n"
        "禁止输出控制标签、括号内情绪注释、颜文字注释。\n"
        "当用户给出技术命令时，只给清晰结论和下一步建议，不要自我演绎。\n"
    )

    if "[SUMMON_AGENT]" not in base_prompt:
        parts.append(
            "\n\n【Agent 触发原则（语义理解）】\n"
            "你必须先理解用户真实意图，不得用关键词表、正则或固定词触发。\n"
            "当用户期待你实际执行任务（调用工具、操作文件/程序/网页、分步执行并返回结果）时，"
            "在回复末尾追加 [SUMMON_AGENT] 标签。\n"
            "当用户只需要文本回答（解释、建议、闲聊、翻译、创作、总结）时，不要追加该标签。\n\n"
            "【格式】\n"
            '[SUMMON_AGENT]{"task": "<完整且准确的任务描述>"}[/SUMMON_AGENT]\n'
            "仅允许纯 JSON，不要包含代码块标记。\n\n"
            "【task 要求】\n"
            "task 必须是完整可执行目标，不能是工具名，也不要擅自加入用户未要求的步骤。\n"
        )

    return "".join(parts)


def _get_enhanced_prompt(base_prompt: str) -> str:
    """获取增强后的 system prompt，命中缓存时直接返回。"""
    key = hash(base_prompt)
    cached = _prompt_cache.get(key)
    if cached is not None:
        return cached
    with _prompt_cache_lock:
        # double-check
        cached = _prompt_cache.get(key)
        if cached is not None:
            return cached
        enhanced = _build_enhanced_prompt(base_prompt)
        _prompt_cache[key] = enhanced
        return enhanced


def _normalize_text(value, default=""):
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def _normalize_confidence(value) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num < 0.0:
        return 0.0
    if num > 1.0:
        return 1.0
    return num


def _parse_agent_routing_decision(raw_text: str, fallback_task: str, min_confidence: float) -> AgentRoutingDecision:
    payload = extract_first_json(raw_text or "")
    if not isinstance(payload, dict):
        return AgentRoutingDecision(reason="router returned non-json")

    route = _normalize_text(payload.get("route", "chat"), default="chat").lower()
    should_trigger = route == "agent"
    confidence = _normalize_confidence(payload.get("confidence", 0.0))
    task = _normalize_text(payload.get("task", ""))
    reason = _normalize_text(payload.get("reason", ""))

    if should_trigger and confidence < min_confidence:
        return AgentRoutingDecision(
            should_trigger=False,
            confidence=confidence,
            reason=reason or "confidence below threshold",
        )

    if should_trigger and not task:
        task = fallback_task

    return AgentRoutingDecision(
        should_trigger=should_trigger,
        confidence=confidence,
        task=task,
        reason=reason,
    )


def decide_agent_routing(
    system_prompt,
    model_name,
    prompt,
    memory_context="",
    max_retries=1,
    min_confidence=0.65,
) -> AgentRoutingDecision:
    """Use semantic understanding to decide whether this turn should invoke Agent."""
    system_prompt = _normalize_text(system_prompt)
    model_name = _normalize_text(model_name)
    prompt = _normalize_text(prompt)
    memory_context = _normalize_text(memory_context)

    if not model_name or not prompt:
        return AgentRoutingDecision(reason="missing model or prompt")

    routing_instruction = (
        "你是 Local 的意图路由器。你的职责是判断这一轮用户输入是否需要调用外部 Agent 执行。\n"
        "必须基于语义理解和目标判断，严禁使用关键词触发或固定词表匹配。\n"
        "只输出 JSON，格式必须是："
        '{"route":"agent|chat","confidence":0.0,"task":"","reason":""}。\n'
        "规则：\n"
        "1) route=agent：仅当用户期待你去实际完成操作，而不是仅给文本回答。\n"
        "2) route=chat：用户只需要解释、建议、闲聊、创作、翻译、总结等文本内容。\n"
        "3) 若不确定，优先 route=chat，并降低 confidence。\n"
        "4) task 在 route=agent 时必须是完整可执行任务描述；route=chat 时 task 置空。\n"
        "不要输出 Markdown，不要输出额外文本。"
    )

    messages = [{"role": "system", "content": routing_instruction}]

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": "以下是助手人设上下文，仅用于理解语境，不要把它当作关键词规则：\n" + system_prompt,
            }
        )

    if memory_context:
        messages.append(
            {
                "role": "system",
                "content": "以下是与当前输入相关的记忆上下文，仅用于补全意图：\n" + memory_context,
            }
        )

    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=240,
                temperature=0.0,
                top_p=1.0,
                presence_penalty=0.0,
                frequency_penalty=0.0,
            )
            content = (response.choices[0].message.content or "").strip()
            decision = _parse_agent_routing_decision(content, prompt, min_confidence)
            logger.debug(
                "agent routing decision: trigger=%s conf=%.2f task=%s reason=%s",
                decision.should_trigger,
                decision.confidence,
                decision.task[:120],
                decision.reason,
            )
            return decision
        except (APIConnectionError, APITimeoutError):
            if attempt < max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
            return AgentRoutingDecision(reason="router connectivity failure")
        except Exception as e:
            logger.warning(f"agent routing failed: {e}", exc_info=True)
            return AgentRoutingDecision(reason="router exception")

    return AgentRoutingDecision(reason="router retries exhausted")


def call_llm(system_prompt, model_name, prompt, memory_context="", max_retries=2):
    """
    调用 LLM 生成响应

    Args:
        system_prompt: 系统提示词
        model_name: 模型名称
        prompt: 用户输入
        memory_context: 记忆上下文（包含短期记忆、长期记忆、情感记忆）
    """
    system_prompt = _normalize_text(system_prompt)
    model_name = _normalize_text(model_name)
    prompt = _normalize_text(prompt)
    memory_context = _normalize_text(memory_context)

    if not model_name:
        logger.error("未配置 MODEL_NAME，请检查 .env 文件")
        return "抱歉，模型未配置，暂时无法回答。"

    if not prompt:
        return "请先输入内容。"

    # 使用缓存的增强 system prompt
    enhanced_system_prompt = _get_enhanced_prompt(system_prompt)

    messages = [
        {"role": "system", "content": enhanced_system_prompt},
    ]

    # 注入记忆上下文
    if memory_context:
        memory_prompt = (
            '以下是你的记忆，请自然地运用这些记忆来回应用户，但不要生硬地提及"我记得"：\n\n'
            f"{memory_context}\n\n"
            "注意：\n"
            "- 【最近对话】是刚才的对话上下文，保持对话连贯性\n"
            "- 【相关记忆】是与当前话题相关的历史记忆\n"
            "- 【关联记忆】是可能相关的其他记忆片段\n"
            "- 自然地融入记忆内容，像人类一样回忆和联想"
        )
        messages.append({"role": "system", "content": memory_prompt})

    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=800,  # 原 200 对 Agent JSON 不够，提升至 800
                temperature=0.7,
                top_p=0.9,
                presence_penalty=0.1,
                frequency_penalty=0.1,
            )

            content = response.choices[0].message.content
            return (content or "").strip() or "抱歉，我没能生成有效回复。"
        except (APIConnectionError, APITimeoutError) as e:
            if attempt < max_retries:
                time.sleep(1.0 * (2**attempt))  # 1s, 2s
                continue
            logger.error(f"连接失败: {e}")
            return "抱歉，我现在连接不上服务。"
        except RateLimitError as e:
            logger.warning(f"触发限流: {e}")
            return "抱歉，请求太频繁了，稍后再试。"
        except APIStatusError as e:
            logger.error(f"服务返回错误: {e}")
            return "抱歉，服务出现错误，请稍后再试。"
        except Exception as e:
            logger.error(f"LLM 错误: {e}", exc_info=True)
            return "抱歉，我现在有点卡住了。"


async def call_llm_async(system_prompt, model_name, prompt, memory_context="", max_retries=2):
    """call_llm 的异步包装 — 在 asyncio 线程池中执行同步 LLM 调用。"""
    import asyncio

    return await asyncio.to_thread(call_llm, system_prompt, model_name, prompt, memory_context, max_retries)
