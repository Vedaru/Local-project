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

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from .config import client
from .logging_config import get_logger

logger = get_logger("llm")

# ---- 缓存已拼装的 system prompt ----
_prompt_cache_lock = threading.Lock()
_prompt_cache: dict = {}  # key: 原始 system_prompt 的 hash -> 拼装后的完整 prompt


def _build_enhanced_prompt(base_prompt: str) -> str:
    """在基础 system prompt 上追加 Agent 触发提示（OpenManus 会自行管理工具描述）。"""
    parts = [base_prompt]

    if "[SUMMON_AGENT]" not in base_prompt:
        parts.append(
            "\n\n【关键任务触发规则】\n"
            "当用户要求以下任何操作时，你必须在回复末尾添加 [SUMMON_AGENT] 标签，且task字段应该准确反映用户的实际需求：\n"
            '• 搜索、查询、查找信息 → task: "搜索..."\n'
            '• 浏览网页、打开网站 → task: "访问...网站并..."\n'
            '• 【重要】生成文件、创建文件、编写代码文件 → task: "生成...文件" (NOT "验证")\n'
            '• 执行代码、运行脚本 → task: "执行代码..."\n'
            '• 操作本地电脑、打开程序 → task: "打开..."\n\n'
            '【格式】在回复末尾添加：[SUMMON_AGENT]{"task": "<完整且准确的任务描述>"}[/SUMMON_AGENT]\n'
            "仅允许纯 JSON，不要包含代码块标记。\n\n"
            "【常见错误】\n"
            '❌ 错误：用户"生成Python文件" → task: "验证这个脚本"\n'
            '✅ 正确：用户"生成Python文件" → task: "生成一个包含输入输出的Python脚本"\n'
            '❌ 错误：用户"写个爬虫" → task: "测试爬虫"\n'
            '✅ 正确：用户"写个爬虫" → task: "编写一个网页爬虫脚本"\n\n'
            "重点：task 字段必须准确反映用户的需求，不要添加额外的验证、测试等步骤。\n"
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
