"""
LLM 模块 - OpenAI 接口
"""
from openai import OpenAI
from .config import client

def call_llm(prompt, memory_context=""):
    """调用 LLM 生成响应"""
    try:
        messages = [
            {"role": "system", "content": "你是一个AI助手。请保持友好、活泼的性格，适当使用一些网络用语。回复要简洁，不要太长。"},
        ]
        
        if memory_context:
            messages.append({"role": "system", "content": f"相关记忆：{memory_context}"})
        
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model="doubao-lite-32k",  # 更新为火山引擎支持的模型名称
            messages=messages,
            max_tokens=200,
            temperature=0.8,
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM错误] {e}")
        return "抱歉，我现在有点卡住了。"