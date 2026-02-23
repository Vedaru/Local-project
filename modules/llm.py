"""
LLM 模块 - OpenAI 接口
支持人类化记忆系统的上下文注入
"""
import time
from openai import APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
from .config import client
from .logging_config import get_logger

# dynamic tool descriptions
# registry resides under the ``agent`` subpackage
from .agent.registry import registry as tool_registry


def _get_tools_knowledge() -> str:
    """返回目前注册工具的提示字符串，用于 system prompt 注入。"""
    return "可用工具及使用说明：\n\n" + tool_registry.get_prompt_description() + "\n"

logger = get_logger('llm')

# 已迁移的 system-prompt 片段（保存在代码中以节省 token；必要时由程序拼接注入）
CORE_PROHIBITIONS = """核心禁令
1. 禁止助人情结：不要自称为“助手”或使用类似措辞。
2. 禁止末尾反问：避免在回复末尾习惯性提问。
3. 禁止过度礼貌：不要频繁使用“谢谢”“不客气”等礼貌短语。
4. 禁止使用括号：尽量避免使用中文或英文圆括号。
5. 禁止 JSON 语音化：不要在语音输出或普通回复中暴露 [ACTION]、[SUMMON_AGENT] 或 {} 等原始标记。
6. **必须言行合一**：如果你在回复中提到你要搜索、点击或打字，你必须在回复的末尾**立即**附加对应的 JSON 指令。
"""

INSTRUCTION_FORMAT = """指令格式规范
- 单步控制 [ACTION] 示例：[ACTION]{"action":"open_local_app","app_path":"notepad"}[/ACTION]（如果是网页可用 browse）
- 复杂任务派发 [SUMMON_AGENT] 示例：[SUMMON_AGENT]{"task":"具体任务描述"}[/SUMMON_AGENT]
"""

# --- 工具知识库（供系统 prompt 注入） ---
# 此段描述当前可用的 AgentTools 函数及其原理，帮助 LLM 理解何时调用它们。


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

    # --- 为了支持本地智能体触发，自动在 system prompt 中追加说明（如果调用端未包含） ---
    # 要求 LLM 在需要本地执行复杂联网 / 本地操作时，在回复末尾添加特殊标签：
    # [SUMMON_AGENT]{"task": "<简明任务描述>"}[/SUMMON_AGENT]
    # 标签内必须是 JSON（仅包含 task 字段或其他必要字段），主程序会检测到并启动 modules.agent 执行。
    # 对于简单的本地命令（例如打开记事本、打开浏览器、运行程序等），请使用 [ACTION] 形式告诉控制器
    # 示例：
    #   [ACTION]{"action":"open_local_app","app_path":"notepad"}[/ACTION]
    # 或者您可以在末尾附加 Agent JSON。
    agent_trigger_hint = (
        "注意：如果用户请求需要联网检索、规划或操作本地电脑的复杂任务，"
        "请在回复末尾以纯 JSON 的形式添加触发标签："
        "[SUMMON_AGENT]{\"task\": \"<简明任务描述>\"}[/SUMMON_AGENT]。"
        "标签内只应包含 JSON，不要包含其他文字。"
        "对于那些仅需启动本地程序的简单命令，您也可以直接使用 [ACTION] 标签，"
        "例如 [ACTION]{\"action\":\"open_local_app\",\"app_path\":\"notepad\"}[/ACTION]。"
    )
    if "[SUMMON_AGENT]" not in system_prompt:
        system_prompt = system_prompt + "\n\n" + agent_trigger_hint


    # --- 工具使用指导 ---
    tool_guidance = (
        "当前可用的工具已在提示词中列出。"
        "在生成回答时，如需执行网络搜索、读取/写入文件或启动本地程序，"
        "请直接调用对应工具。"
        "例如，当用户说“打开笔记本”或“打开记事本”时，应该返回 JSON {\"tool\":\"open_local_app\",\"args\":\"notepad\"}。"
        "当用户要求写日志或写一段文字到笔记本时，可直接使用 open_local_app 然后 type_text。"
    )
    if tool_guidance not in system_prompt:
        # 插入最新的工具说明，而不是使用静态 TOOLS_KNOWLEDGE
        system_prompt = system_prompt + "\n\n" + tool_guidance + "\n\n" + _get_tools_knowledge()

    if not model_name:
        logger.error("未配置 MODEL_NAME，请检查 .env 文件")
        return "抱歉，模型未配置，暂时无法回答。"

    if not prompt:
        return "请先输入内容。"

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # 注入记忆上下文
    if memory_context:
        memory_prompt = f"""以下是你的记忆，请自然地运用这些记忆来回应用户，但不要生硬地提及"我记得"：

{memory_context}

注意：
- 【最近对话】是刚才的对话上下文，保持对话连贯性
- 【相关记忆】是与当前话题相关的历史记忆
- 【关联记忆】是可能相关的其他记忆片段
- 自然地融入记忆内容，像人类一样回忆和联想"""
        messages.append({"role": "system", "content": memory_prompt})

    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=200,
                temperature=0.7,      # 压制幻觉的关键：不要超过 0.8
                top_p=0.9,            # 限制词池范围，防止跑题
                presence_penalty=0.1, # 稍微鼓励谈论新话题，但不要太高
                frequency_penalty=0.1
            )

            content = response.choices[0].message.content
            return (content or "").strip() or "抱歉，我没能生成有效回复。"
        except (APIConnectionError, APITimeoutError) as e:
            if attempt < max_retries:
                time.sleep(1.5 * (2 ** attempt))
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
