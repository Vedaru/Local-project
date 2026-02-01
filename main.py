"""
Project Seeka - 主入口文件
"""
import signal
import sys
from modules.memory import MemoryManager
from modules.memory.logger import get_logger
from modules.voice import VoiceManager
from modules.llm import call_llm
from modules.config import REF_AUDIO, PROMPT_TEXT, SOVITS_URL, GPT_SOVITS_PATH, MODEL_NAME, SYSTEM_PROMPT
from modules.utils import clean_text, start_gpt_sovits_api, check_sovits_service

# 全局变量用于信号处理
memory_manager = None
sovits_process = None

def signal_handler(sig, frame):
    """处理 Ctrl+C 信号，确保记忆被保存"""
    if memory_manager:
        memory_manager.summarize_day()
        memory_manager.close()
    if sovits_process:
        sovits_process.terminate()
        sovits_process.wait()
    sys.exit(0)

def main():
    global memory_manager, sovits_process

    memory_logger = get_logger()
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 启动 GPT-SoVITS API 服务
    sovits_process = start_gpt_sovits_api(GPT_SOVITS_PATH)
    if sovits_process is None:
        print("警告: GPT-SoVITS API 服务启动失败。请检查 GPT_SOVITS_PATH 环境变量和 GPT-SoVITS 安装。")
        print("您可以手动启动 GPT-SoVITS 服务，或按 Enter 继续（语音功能将不可用）。")
        input("按 Enter 继续...")
    
    # 初始化模块
    memory_manager = MemoryManager()
    graph_memory = GraphMemory()
    voice_manager = VoiceManager(
        sovits_url=SOVITS_URL,
        ref_audio=REF_AUDIO,
        prompt_text=PROMPT_TEXT,
    )
    
    # 启动时清理记忆（模拟自然遗忘）
    memory_manager.cleanup_old_memories()
    
    # 显示记忆系统状态
    stats = memory_manager.get_memory_stats()
    print(f"\n📊 记忆状态: 短期({stats['short_term']}/{stats['short_term_capacity']}) | "
          f"工作({stats['working_memory']}) | 长期({stats['long_term']}) | 情感({stats['emotional']})")
    
    print("\nProject Local 已启动。输入 'exit' 或 'quit' 退出，输入 'status' 查看记忆状态。")
    
    while True:
        user_input = input("\n你: ")
        
        # 特殊命令处理
        if user_input.lower() in ['exit', 'quit']:
            # 退出前生成每日总结并保存所有记忆
            memory_manager.summarize_day()
            memory_manager.close()  # 确保所有记忆都已保存
            break
        
        if user_input.lower() == 'status':
            stats = memory_manager.get_memory_stats()
            print(f"\n📊 记忆系统状态:")
            print(f"  ├─ 短期记忆: {stats['short_term']}/{stats['short_term_capacity']} 轮")
            print(f"  ├─ 工作记忆: {stats['working_memory']} 条")
            print(f"  ├─ 长期记忆: {stats['long_term']} 条")
            print(f"  ├─ 情感记忆: {stats['emotional']} 条")
            print(f"  └─ 当前情感: {stats['current_emotion']}")
            continue
        
        # 清理输入文本
        cleaned_input = clean_text(user_input)

        # 语义图谱摄取（可解释记忆）
        graph_memory.ingest_utterance(cleaned_input, speaker="用户", source="dialog")
        
        # 添加到短期记忆
        memory_manager.add_to_short_term("用户", cleaned_input)
        
        # 检索相关记忆（多层次）
        memory_context = memory_manager.retrieve_memories(cleaned_input)
        if memory_context == "无相关记忆。":
            memory_context = ""  # 不传递无记忆的上下文
        
        # 调用 LLM 生成响应
        ai_response = call_llm(SYSTEM_PROMPT, MODEL_NAME, cleaned_input, memory_context)
        
        explain_lines = graph_memory.explain_latest()
        if explain_lines:
            memory_logger.info("[可解释链] " + " | ".join(explain_lines))

        print(f"AI: {ai_response}")
        
        # 只有在非错误响应时才处理记忆
        if ai_response != "抱歉，我现在有点卡住了。":
            # 添加AI响应到短期记忆
            memory_manager.add_to_short_term("AI", ai_response)
            
            # 存储完整对话到长期记忆系统
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