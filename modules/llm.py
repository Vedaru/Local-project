"""
LLM 模块 - OpenAI 接口
支持人类化记忆系统的上下文注入

优化点：
- 缓存拼装好的 system prompt，避免每次调用都重复拼接
- 移除未使用的 CORE_PROHIBITIONS / INSTRUCTION_FORMAT 死代码
- max_tokens 从 200 提升到 800（200 对 Agent JSON 输出远远不够）
- 指数退避首次间隔从 1.5s 降到 1.0s
"""
import threading
import time
from openai import APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
from .config import client
from .logging_config import get_logger

# 动态工具描述 — registry 位于 agent 子包
from .agent.registry import registry as tool_registry

logger = get_logger('llm')

# ---- 缓存已拼装的 system prompt ----
_prompt_cache_lock = threading.Lock()
_prompt_cache: dict = {}  # key: 原始 system_prompt 的 hash -> 拼装后的完整 prompt


def _build_enhanced_prompt(base_prompt: str) -> str:
    """在基础 system prompt 上追加 Agent 触发提示与工具说明（仅在首次时构建）。"""
    parts = [base_prompt]

    if "[SUMMON_AGENT]" not in base_prompt:
        parts.append(
            "\n\n注意：如果用户请求需要联网检索、搜索信息、浏览网页、或操作本地电脑的任务，"
            "请在回复末尾以纯 JSON 的形式添加触发标签："
            '[SUMMON_AGENT]{"task": "<简明任务描述>"}[/SUMMON_AGENT]。'
            "标签内只应包含 JSON，不要包含其他文字。\n"
            "【重要】当用户让你搜索、查询、查找信息时，你必须使用 [SUMMON_AGENT] 标签来触发 Agent 执行搜索，"
            "而不是口头描述搜索步骤。例如：\n"
            "用户：帮我搜一下今天的天气\n"
            '回复：好的，我来帮你搜索一下~ [SUMMON_AGENT]{"task":"搜索今天的天气预报"}[/SUMMON_AGENT]\n'
            "用户：打开B站搜索猫猫视频\n"
            '回复：好嘞，我去B站找找~ [SUMMON_AGENT]{"task":"打开B站并搜索猫猫视频"}[/SUMMON_AGENT]\n'
            "对于那些仅需启动本地程序的简单命令，您也可以直接使用 [ACTION] 标签，"
            '例如 [ACTION]{"action":"open_local_app","app_path":"notepad"}[/ACTION]。'
        )

    tool_guidance = (
        "当前可用的工具已在提示词中列出。"
        "当用户要求搜索、查询、浏览网页或执行需要多个步骤的操作时，"
        "必须使用 [SUMMON_AGENT] 标签触发 Agent 来执行，不要只是口头描述步骤。"
        "对于简单的单步操作（如打开记事本），可以直接返回 JSON 工具调用。"
        '例如，当用户说"打开笔记本"或"打开记事本"时，应该返回 JSON {"tool":"open_local_app","args":"notepad"}。'
        "当用户要求写日志或写一段文字到笔记本时，可直接使用 open_local_app 然后 type_text。\n"
        "【重要：网页输入规范】在网页的输入框中输入文字时，必须先执行 click_element 点击/聚焦输入框，"
        "再执行 type_text 输入文字，最后执行 press_key Enter 提交。"
        "切勿跳过 click_element 直接 type_text，否则键盘事件无目标、文字会丢失。"
        "例如在B站搜索：先 browse 打开B站，再 click_element nav-search-input，再 type_text 关键词，再 press_key Enter。"
    )
    if tool_guidance not in base_prompt:
        tools_knowledge = "可用工具及使用说明：\n\n" + tool_registry.get_prompt_description() + "\n"
        parts.append("\n\n" + tool_guidance + "\n\n" + tools_knowledge)

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
            "以下是你的记忆，请自然地运用这些记忆来回应用户，但不要生硬地提及\"我记得\"：\n\n"
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
                max_tokens=800,           # 原 200 对 Agent JSON 不够，提升至 800
                temperature=0.7,
                top_p=0.9,
                presence_penalty=0.1,
                frequency_penalty=0.1,
            )

            content = response.choices[0].message.content
            return (content or "").strip() or "抱歉，我没能生成有效回复。"
        except (APIConnectionError, APITimeoutError) as e:
            if attempt < max_retries:
                time.sleep(1.0 * (2 ** attempt))  # 1s, 2s
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
