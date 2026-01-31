"""
LLM 模块 - OpenAI 接口
"""
from openai import OpenAI
from .config import client

def call_llm(system_prompt, model_name, prompt, memory_context=""):
    """调用 LLM 生成响应"""
    try:
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        if memory_context:
            messages.append({"role": "system", "content": f"相关记忆：{memory_context}"})
        
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=model_name,  # 更新为火山引擎支持的模型名称
            messages=messages,
            max_tokens=200,
            temperature=0.8,
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM错误] {e}")
        return "抱歉，我现在有点卡住了。"