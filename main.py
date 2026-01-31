"""
Project Seeka - 主入口文件
"""

from modules.memory import MemoryManager
from modules.voice import VoiceManager
from modules.llm import call_llm
from modules.config import REF_AUDIO, PROMPT_TEXT, SOVITS_URL, GPT_SOVITS_PATH, MODEL_NAME, SYSTEM_PROMPT
from modules.utils import clean_text, start_gpt_sovits_api, check_sovits_service

def main():
    # 启动 GPT-SoVITS API 服务
    sovits_process = start_gpt_sovits_api(GPT_SOVITS_PATH)
    if sovits_process is None:
        print("警告: GPT-SoVITS API 服务启动失败。请检查 GPT_SOVITS_PATH 环境变量和 GPT-SoVITS 安装。")
        print("您可以手动启动 GPT-SoVITS 服务，或按 Enter 继续（语音功能将不可用）。")
        input("按 Enter 继续...")
    
    # 初始化模块
    memory_manager = MemoryManager()
    voice_manager = VoiceManager(
        sovits_url=SOVITS_URL,
        ref_audio=REF_AUDIO,
        prompt_text=PROMPT_TEXT,
    )
    
    # 启动时清理记忆
    memory_manager.cleanup_old_memories()
    
    print("Project Local 已启动。输入 'exit' 或 'quit' 退出。")
    
    while True:
        user_input = input("\n你: ")
        if user_input.lower() in ['exit', 'quit']:
            break
        
        # 清理输入文本
        cleaned_input = clean_text(user_input)
        
        # 检索相关记忆
        memory_context = memory_manager.retrieve_memories(cleaned_input)
        if memory_context == "无相关记忆。":
            memory_context = ""  # 不传递无记忆的上下文
        
        # 调用 LLM 生成响应
        ai_response = call_llm(SYSTEM_PROMPT, MODEL_NAME, cleaned_input, memory_context)
        
        print(f"AI: {ai_response}")
        
        # 只有在非错误响应时才存储记忆
        if ai_response != "抱歉，我现在有点卡住了。":
            memory_manager.store_memory(f"用户: {cleaned_input}\nAI: {ai_response}")
        
        # 语音合成
        voice_manager.speak(ai_response)
    
    # 退出时停止 GPT-SoVITS 进程
    if sovits_process:
        sovits_process.terminate()
        sovits_process.wait()
        print("GPT-SoVITS API 服务已停止。")

if __name__ == "__main__":
    main()