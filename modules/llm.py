"""
LLM 模块 - OpenAI 接口
支持人类化记忆系统的上下文注入
"""
import time
from openai import APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
from .config import client

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
        print("[LLM错误] 未配置 MODEL_NAME，请检查 .env 文件")
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
                temperature=0.8,
            )

            content = response.choices[0].message.content
            return (content or "").strip() or "抱歉，我没能生成有效回复。"
        except (APIConnectionError, APITimeoutError) as e:
            if attempt < max_retries:
                time.sleep(1.5 * (2 ** attempt))
                continue
            print(f"[LLM错误] 连接失败: {e}")
            return "抱歉，我现在连接不上服务。"
        except RateLimitError as e:
            print(f"[LLM错误] 触发限流: {e}")
            return "抱歉，请求太频繁了，稍后再试。"
        except APIStatusError as e:
            print(f"[LLM错误] 服务返回错误: {e}")
            return "抱歉，服务出现错误，请稍后再试。"
        except Exception as e:
            print(f"[LLM错误] {e}")
            return "抱歉，我现在有点卡住了。"