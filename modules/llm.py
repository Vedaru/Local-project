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

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError as OpenAIRateLimitError

from .config import client
from .json_utils import extract_first_json
from .logging_config import get_logger
from .resilience import (
    RateLimitError as LocalRateLimitError,
    ServiceUnavailableError,
)

logger = get_logger("llm")


# ---- OpenAI 异常到自定义异常的映射 ----
def _translate_openai_error(e: Exception) -> Exception:
    """将 OpenAI SDK 异常映射为 resilience 自定义异常，供调用方统一处理。"""
    if isinstance(e, (APIConnectionError, APITimeoutError)):
        return ServiceUnavailableError(
            service_name="llm",
            message=str(e),
        )
    if isinstance(e, OpenAIRateLimitError):
        return LocalRateLimitError(service_name="llm")
    if isinstance(e, APIStatusError):
        return ServiceUnavailableError(
            service_name="llm",
            message=f"HTTP {e.status_code}: {e.message}",
        )
    return e  # 其他异常原样返回


@dataclass(frozen=True)
class AgentRoutingDecision:
    """Semantic routing decision for whether a user turn should invoke Agent."""

    should_trigger: bool = False
    confidence: float = 0.0
    task: str = ""
    reason: str = ""
    is_atomic: bool = True

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


def _normalize_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _normalize_text(value, default="").lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


_MUTEX_GOAL_KEYWORD_PAIRS = (
    ("打开", "关闭"),
    ("启用", "禁用"),
    ("启动", "停止"),
    ("增加", "减少"),
    ("安装", "卸载"),
    ("create", "delete"),
    ("enable", "disable"),
    ("start", "stop"),
)


def _has_mutually_exclusive_goals(task: str) -> bool:
    normalized = _normalize_text(task, default="").lower()
    if not normalized:
        return False
    for left, right in _MUTEX_GOAL_KEYWORD_PAIRS:
        if left in normalized and right in normalized:
            return True
    return False


def _parse_agent_routing_decision(
    raw_text: str,
    fallback_task: str,
    min_confidence: float,
) -> tuple[AgentRoutingDecision, str]:
    payload = extract_first_json(raw_text or "")
    if not isinstance(payload, dict):
        return AgentRoutingDecision(reason="router returned non-json"), "router returned non-json"

    route = _normalize_text(payload.get("route", "chat"), default="chat").lower()
    should_trigger = route == "agent"
    confidence = _normalize_confidence(payload.get("confidence", 0.0))
    task = _normalize_text(payload.get("task", ""))
    reason = _normalize_text(payload.get("reason", ""))
    is_atomic = _normalize_bool(payload.get("is_atomic", True), default=True)

    if should_trigger and not task:
        task = fallback_task

    # 本地原子性校验：即使模型未输出 is_atomic，也进行保底互斥目标检查。
    if should_trigger and _has_mutually_exclusive_goals(task):
        is_atomic = False
        reason = reason or "任务包含互斥目标"

    if should_trigger and confidence < min_confidence:
        return AgentRoutingDecision(
            should_trigger=False,
            confidence=confidence,
            reason=reason or "confidence below threshold",
            is_atomic=is_atomic,
        ), ""

    if should_trigger and not is_atomic:
        return AgentRoutingDecision(
            should_trigger=False,
            confidence=confidence,
            task=task,
            reason=reason or "任务包含多个互斥目标，请拆分后再试",
            is_atomic=False,
        ), ""

    return AgentRoutingDecision(
        should_trigger=should_trigger,
        confidence=confidence,
        task=task,
        reason=reason,
        is_atomic=is_atomic,
    ), ""


def _reverse_validate_agent_route(
    model_name: str,
    prompt: str,
    task: str,
    confidence: float,
    reason: str,
) -> AgentRoutingDecision:
    """Second-pass guardrail for medium-confidence agent decisions."""
    validation_instruction = (
        "你是路由反向校验器。请判断该输入是否真的需要调用工具执行。\n"
        "如果其实是闲聊/解释/建议，必须纠正为 chat。\n"
        "只输出 JSON，格式: "
        '{"route":"agent|chat","confidence":0.0,"reason":""}。\n'
        "不要输出额外文本。"
    )

    messages = [
        {"role": "system", "content": validation_instruction},
        {
            "role": "user",
            "content": (
                "反向验证问题：你确定这个任务需要调用工具吗？如果是闲聊请纠正。\n"
                f"用户输入: {prompt}\n"
                f"初始判断: route=agent, confidence={confidence:.2f}, task={task}, reason={reason}"
            ),
        },
    ]

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=160,
            temperature=0.0,
            top_p=1.0,
            presence_penalty=0.0,
            frequency_penalty=0.0,
            response_format={"type": "json_object"},
        )
        content = (response.choices[0].message.content or "").strip()
        payload = extract_first_json(content)
        if not isinstance(payload, dict):
            return AgentRoutingDecision(
                should_trigger=True,
                confidence=confidence,
                task=task,
                reason=f"{reason}|reverse-validator-non-json",
                is_atomic=True,
            )

        route = _normalize_text(payload.get("route", "chat"), default="chat").lower()
        revised_confidence = _normalize_confidence(payload.get("confidence", confidence))
        revised_reason = _normalize_text(payload.get("reason", ""))
        if route != "agent":
            return AgentRoutingDecision(
                should_trigger=False,
                confidence=revised_confidence,
                reason=revised_reason or "reverse validator corrected to chat",
                is_atomic=True,
            )
        return AgentRoutingDecision(
            should_trigger=True,
            confidence=max(confidence, revised_confidence),
            task=task,
            reason=revised_reason or reason or "reverse validator confirmed agent",
            is_atomic=True,
        )
    except Exception as exc:
        logger.debug("reverse validation skipped: %s", exc)
        return AgentRoutingDecision(
            should_trigger=True,
            confidence=confidence,
            task=task,
            reason=f"{reason}|reverse-validation-error",
            is_atomic=True,
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
        '{"route":"agent|chat","confidence":0.0,"task":"","reason":"","is_atomic":true}。\n'
        "规则：\n"
        "1) route=agent：仅当用户期待你去实际完成操作，而不是仅给文本回答。\n"
        "2) route=chat：用户只需要解释、建议、闲聊、创作、翻译、总结等文本内容。\n"
        "3) 若不确定，优先 route=chat，并降低 confidence。\n"
        "4) task 在 route=agent 时必须是完整可执行任务描述；route=chat 时 task 置空。\n"
        "5) 如果 task 含多个互斥目标（例如同时要求开启和关闭同一对象），is_atomic 必须为 false。\n"
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

    parse_feedback = ""
    for attempt in range(max_retries + 1):
        try:
            strict_json_mode = attempt > 0
            attempt_messages = list(messages)
            if strict_json_mode and parse_feedback:
                attempt_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "上一次输出无法解析为有效 JSON。错误反馈："
                            f"{parse_feedback}。请严格只输出 JSON 对象，不要附加解释。"
                        ),
                    }
                )

            request_kwargs = {}
            if strict_json_mode:
                request_kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(
                model=model_name,
                messages=attempt_messages,
                max_tokens=240,
                temperature=0.0,
                top_p=1.0,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                **request_kwargs,
            )
            content = (response.choices[0].message.content or "").strip()
            decision, parse_error = _parse_agent_routing_decision(content, prompt, min_confidence)
            if parse_error:
                parse_feedback = parse_error
                if attempt < max_retries:
                    continue
                return AgentRoutingDecision(reason=parse_error)

            if decision.should_trigger and 0.65 <= decision.confidence <= 0.8:
                revised = _reverse_validate_agent_route(
                    model_name=model_name,
                    prompt=prompt,
                    task=decision.task,
                    confidence=decision.confidence,
                    reason=decision.reason,
                )
                if not revised.should_trigger:
                    return revised
                decision = revised

            logger.debug(
                "agent routing decision: trigger=%s conf=%.2f atomic=%s task=%s reason=%s",
                decision.should_trigger,
                decision.confidence,
                decision.is_atomic,
                decision.task[:120],
                decision.reason,
            )
            return decision
        except TypeError as e:
            # 部分后端不支持 response_format。降级为提示词纠错重试。
            if attempt < max_retries:
                parse_feedback = f"json_mode unsupported: {e}"
                continue
            return AgentRoutingDecision(reason="router type error")
        except (APIConnectionError, APITimeoutError):
            if attempt < max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
            return AgentRoutingDecision(reason="router connectivity failure")
        except Exception as e:
            logger.warning("agent routing failed: %s", e, exc_info=True)
            return AgentRoutingDecision(reason="router exception")

    return AgentRoutingDecision(reason="router retries exhausted")


def _extract_completed_sentences(buffer: str) -> tuple[list[str], str]:
    completed: list[str] = []
    if not buffer:
        return completed, ""

    start = 0
    for idx, ch in enumerate(buffer):
        if ch in "。！？!?；;\n":
            sentence = buffer[start: idx + 1].strip()
            if sentence:
                completed.append(sentence)
            start = idx + 1

    return completed, buffer[start:]


def call_llm_with_sentence_callback(
    system_prompt,
    model_name,
    prompt,
    memory_context="",
    on_sentence=None,
    max_retries=2,
):
    """Stream completion text and emit complete sentences as soon as they are formed."""
    if not callable(on_sentence):
        return call_llm(system_prompt, model_name, prompt, memory_context, max_retries)

    system_prompt = _normalize_text(system_prompt)
    model_name = _normalize_text(model_name)
    prompt = _normalize_text(prompt)
    memory_context = _normalize_text(memory_context)

    if not model_name or not prompt:
        return call_llm(system_prompt, model_name, prompt, memory_context, max_retries)

    enhanced_system_prompt = _get_enhanced_prompt(system_prompt)
    messages = [{"role": "system", "content": enhanced_system_prompt}]

    if memory_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是与你当前用户相关的记忆上下文。仅当与当前输入语义相关时再参考；"
                    "若相关性弱，请忽略这些记忆并按当前输入自然作答。\n\n"
                    f"{memory_context}"
                ),
            }
        )
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=800,
                temperature=0.7,
                top_p=0.9,
                presence_penalty=0.1,
                frequency_penalty=0.1,
                stream=True,
            )

            all_text = ""
            sentence_buffer = ""
            for chunk in response:
                try:
                    chunk_text = chunk.choices[0].delta.content or ""
                except Exception:
                    chunk_text = ""
                if not chunk_text:
                    continue

                all_text += chunk_text
                sentence_buffer += chunk_text
                completed, sentence_buffer = _extract_completed_sentences(sentence_buffer)
                for sentence in completed:
                    try:
                        on_sentence(sentence)
                    except Exception as exc:
                        logger.debug("sentence callback failed: %s", exc)

            tail = sentence_buffer.strip()
            if tail:
                try:
                    on_sentence(tail)
                except Exception as exc:
                    logger.debug("sentence callback failed on tail: %s", exc)

            final_text = all_text.strip()
            if final_text:
                return final_text
            return "抱歉，我没能生成有效回复。"
        except OpenAIRateLimitError as e:
            logger.warning("触发限流: %s", e)
            if attempt < max_retries:
                time.sleep(1.0 * (2**attempt))
                continue
            break
        except (APIConnectionError, APITimeoutError) as e:
            translated = _translate_openai_error(e)
            if attempt < max_retries:
                logger.warning("LLM流式连接异常(将重试 %d/%d): %s", attempt + 1, max_retries, translated.message)
                time.sleep(1.0 * (2**attempt))
                continue
            break
        except Exception as exc:
            logger.warning("流式LLM失败，回退普通调用: %s", exc)
            break

    return call_llm(system_prompt, model_name, prompt, memory_context, max_retries)


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
            "以下是与你当前用户相关的记忆上下文。仅当与当前输入语义相关时再参考；"
            "若相关性弱，请忽略这些记忆并按当前输入自然作答。\n\n"
            f"{memory_context}\n\n"
            "回答规则：\n"
            "- 仅在记忆与当前问题明显相关时使用记忆事实，禁止为了引用记忆而强行转移话题\n"
            "- 事实性问题优先使用记忆中的明确事实，尤其是用户偏好、习惯和近期确认的信息\n"
            "- 记忆冲突时按优先级处理：最近对话 > 已知事实 > 历史对话(用户输入) > 相关记忆\n"
            "- 若记忆中没有足够依据，直接说明不确定，并向用户追问，不要猜测\n"
            "- 表达自然，不要机械复述“我记得”或逐段引用标题"
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
        except OpenAIRateLimitError as e:
            logger.warning("触发限流: %s", e)
            if attempt < max_retries:
                time.sleep(1.0 * (2**attempt))
                continue
            return "抱歉，请求太频繁了，稍后再试。"
        except (APIConnectionError, APITimeoutError) as e:
            translated = _translate_openai_error(e)
            if attempt < max_retries:
                logger.warning("LLM 连接异常(将重试 %d/%d): %s", attempt + 1, max_retries, translated.message)
                time.sleep(1.0 * (2**attempt))
                continue
            logger.error("连接失败: %s", translated.message)
            return "抱歉，我现在连接不上服务。"
        except APIStatusError as e:
            translated = _translate_openai_error(e)
            logger.error("服务返回错误: %s", translated.message)
            return "抱歉，服务出现错误，请稍后再试。"


async def call_llm_async(system_prompt, model_name, prompt, memory_context="", max_retries=2):
    """call_llm 的异步包装 — 在 asyncio 线程池中执行同步 LLM 调用。"""
    import asyncio

    return await asyncio.to_thread(call_llm, system_prompt, model_name, prompt, memory_context, max_retries)
