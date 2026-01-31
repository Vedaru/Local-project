"""
Project Seeka - 主入口文件
"""

from modules.memory import MemoryManager
from modules.voice import VoiceManager
from modules.llm import call_llm
from modules.config import REF_AUDIO, PROMPT_TEXT, SOVITS_URL
from modules.utils import clean_text

def main():
    # 初始化模块
    memory_manager = MemoryManager()
    voice_manager = VoiceManager(
        sovits_url=SOVITS_URL,
        ref_audio=REF_AUDIO,
        prompt_text=PROMPT_TEXT
    )
    
    # 启动时清理记忆
    memory_manager.cleanup_old_memories()
    
    print("Project Seeka 已启动。输入 'exit' 或 'quit' 退出。")
    
    while True:
        user_input = input("\n你: ")
        if user_input.lower() in ['exit', 'quit']:
            break
        
        # 清理输入文本
        cleaned_input = clean_text(user_input)
        
        # 检索相关记忆
        memory_context = memory_manager.retrieve_memories(cleaned_input)
        
        # 调用 LLM 生成响应
        ai_response = call_llm(cleaned_input, memory_context)
        
        print(f"AI: {ai_response}")
        
        # 存储记忆
        memory_manager.store_memory(f"用户: {cleaned_input}\nAI: {ai_response}")
        
        # 语音合成
        voice_manager.speak(ai_response)

if __name__ == "__main__":
    main()