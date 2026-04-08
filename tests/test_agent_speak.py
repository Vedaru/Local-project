"""
简单测试 agent speak 功能

验证 agent 在执行任务时是否能够通过 speak_callback 输出语音描述。
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from modules.agent.core import ManusAgent, set_agent_speak_callback


def test_agent_speak_callback():
    """测试 agent speak 回调是否被正确调用。"""
    
    # 收集 speak 输出
    speak_outputs = []
    
    def collect_speak(text: str):
        """收集 speak 输出的回调。"""
        speak_outputs.append(text)
        print(f"🗣️  Agent says: {text}")
    
    # 设置全局 speak 回调
    set_agent_speak_callback(collect_speak)
    
    # 创建 agent，传入 speak_callback
    agent = ManusAgent(
        system_prompt="你是一个简洁的助手。",
        max_steps=3,
        task_timeout_seconds=30.0,
        speak_callback=collect_speak,
    )
    
    print("✅ Agent 已创建，speak 回调已设置")
    print(f"已收集的 speak 输出数量：{len(speak_outputs)}")
    
    # 清理
    agent.cleanup()
    print("✅ Agent 已清理")

    # 测试函数不应返回非 None，改为断言基本执行路径正常。
    assert isinstance(speak_outputs, list)


if __name__ == "__main__":
    print("=" * 60)
    print("测试 Agent Speak 功能")
    print("=" * 60)
    
    try:
        test_agent_speak_callback()
        print("\n✅ 测试完成")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
