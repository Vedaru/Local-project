"""
LLM 模块 - OpenAI 接口
支持人类化记忆系统的上下文注入
"""
from openai import OpenAI
from .config import client

def call_llm(system_prompt, model_name, prompt, memory_context=""):
    """
    调用 LLM 生成响应
    
    Args:
        system_prompt: 系统提示词
        model_name: 模型名称
        prompt: 用户输入
        memory_context: 记忆上下文（包含短期记忆、长期记忆、情感记忆）
    """
    try:
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
        
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=200,
            temperature=0.8,
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM错误] {e}")
        return "抱歉，我现在有点卡住了。"