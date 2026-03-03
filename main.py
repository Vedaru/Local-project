"""
Project Local - 带 Avatar 虚拟形象的主入口文件
演示如何将 PyQt6 GUI 与 AI 逻辑在不同线程中集成
"""
import signal
import sys
import os

# 必须在导入任何其他模块前设置环境变量（修复 ctranslate2 的 ROCm 路径问题）
os.environ["CT2_USE_CUDA"] = "0"

import re
import json
import threading
import queue
import tempfile
import time
import wave
from typing import Optional, Any

from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from modules.avatar import AvatarWidget, AvatarManager
from modules.avatar import LipSyncManager, ExpressionManager, Emotion
from modules.avatar.logger import log_info as avatar_log_info
from modules.memory import MemoryManager
from modules.voice import VoiceManager
from modules.ear import Ear
from modules.llm import call_llm
# Agent 模块（基于 OpenManus 框架的智能体）
from modules.agent.core import ManusAgent
from modules.config import REF_AUDIO, PROMPT_TEXT, SOVITS_URL, GPT_SOVITS_PATH, MODEL_NAME, SYSTEM_PROMPT
from modules.utils import clean_text, start_gpt_sovits_api, check_sovits_service, filter_emotion_tags
from modules.logging_config import get_logger
from modules.json_utils import extract_first_json


class AIWorkerSignals(QObject):
    """AI 工作线程的信号定义，用于与主线程通信"""
    response_ready = pyqtSignal(str)        # AI 响应就绪
    lip_sync_update = pyqtSignal(float)     # 口型同步更新
    expression_change = pyqtSignal(object)  # 表情变化（接收 Emotion 枚举或字符串）
    motion_play = pyqtSignal(str, int)      # 播放动作
    status_update = pyqtSignal(str)         # 状态更新
    shutdown = pyqtSignal()                 # 关闭信号
    speak_request = pyqtSignal(str)         # 语音合成请求（带口型同步）
    play_audio = pyqtSignal(str)            # 播放音频请求（wav 文件路径）
    ear_recognized = pyqtSignal(str)        # 麦克风识别结果（来自 Ear 模块）


class EarWorker(threading.Thread):
    """
    Ear 工作线程：在后台线程中运行麦克风监听
    识别到文本后通过队列发送给 AIWorker 处理
    暂时禁用
    """
    
    def __init__(self, input_queue: queue.Queue, model_size: str = "base"):
        super().__init__(daemon=True)
        self.input_queue = input_queue
        self.model_size = model_size
        self.ear = None
        self._running = True
    
    def run(self):
        """线程主循环"""
        logger = get_logger('Ear')  # 使用 Ear logger，而不是 MainApplication
        try:
            logger.info(f"🎙️  初始化听觉模块，模型大小: {self.model_size}")
            self.ear = Ear(model_size=self.model_size)
            
            def on_text_recognized(text: str):
                """当识别到文本时，发送到 AIWorker 的输入队列"""
                if self._running and text.strip():
                    logger.info(f"🎯 识别结果: {text}")
                    self.input_queue.put(text)
            
            # 开始阻塞监听麦克风
            # Ear 模块会输出其自己的监听日志
            self.ear.listen(callback=on_text_recognized)
            
        except Exception as e:
            logger.error(f"❌ 错误: {e}", exc_info=True)
        finally:
            if self.ear:
                self.ear.close()
            logger.info("🛑 听觉模块已关闭")
    
    def stop(self):
        """停止监听"""
        self._running = False
        if self.ear:
            self.ear.stop()


class AIWorker(threading.Thread):
    """
    AI 工作线程
    处理用户输入、调用 LLM、语音合成等 AI 逻辑
    通过信号与主线程的 GUI 通信
    """
    
    def __init__(
        self,
        signals: AIWorkerSignals,
        input_queue: queue.Queue,
        memory_manager: MemoryManager,
        voice_manager: VoiceManager,
        agent: Optional[ManusAgent] = None
    ):
        super().__init__(daemon=True)
        self.signals = signals
        self.input_queue = input_queue
        self.memory_manager = memory_manager
        self.voice_manager = voice_manager
        self.agent = agent
        self._running = True
        # 当模型因“人设/拒绝”而中断任务时，在下一轮强制提醒它继续未完成的任务
        self._force_continue_next = False
        self._force_lock = threading.Lock()  # 保护 _force_continue_next 的线程安全
    
    def run(self):
        """线程主循环"""
        logger = get_logger('AIWorker')
        while self._running:
            try:
                # 等待用户输入（带超时，便于检查 _running 状态）
                try:
                    user_input = self.input_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if user_input is None:  # 退出信号
                    break
                
                # 处理特殊命令
                if user_input.lower() in ['exit', 'quit']:
                    self.signals.shutdown.emit()
                    break
                
                if user_input.lower() == 'status':
                    stats = self.memory_manager.get_memory_stats()
                    status_msg = (
                        f"📊 记忆系统状态:\n"
                        f"  ├─ 对话轮次: {stats['short_term']}/{stats['short_term_capacity']} 轮\n"
                        f"  ├─ 短期交互: {stats['working_memory']} 条\n"
                        f"  ├─ 长期记忆: {stats['long_term']} 条\n"
                        f"  └─ 概念节点: {stats.get('concept_nodes', 0)} 个"
                    )
                    self.signals.status_update.emit(status_msg)
                    continue
                
                # 清理输入文本
                cleaned_input = clean_text(user_input)
                
                # 跳过空输入
                if not cleaned_input.strip():
                    continue

                # -------- 教学模式触发 --------

                # 识别各种表达“我来教你/我要教你/开始教学”的语句
                if re.search(r'(?:开始教学|我要教你|我(?:来)?教你|来教你)', cleaned_input):
                    m = re.search(r'(?:开始教学|我要教你|我(?:来)?教你|来教你)(.*)', cleaned_input)
                    task_name = m.group(1).strip() if m else ""
                    if self.agent:
                        _ = self.agent.start_learning(task_name)
                        msg = "好的，进入教学模式，请演示一遍给我看。"
                    else:
                        msg = "⚠️ Agent 未初始化，无法进入教学模式。"
                    # 语音 + 文本响应都发出，以便界面恢复可输入状态
                    self.signals.speak_request.emit(msg)
                    self.signals.response_ready.emit(msg)
                    continue

                if any(kw in cleaned_input for kw in ("教学结束", "学会了吗")):
                    if self.agent:
                        result = self.agent.stop_learning()
                    else:
                        result = "⚠️ Agent 未初始化，无法结束教学。"
                    self.signals.speak_request.emit(result)
                    self.signals.response_ready.emit(result)
                    continue

                # 添加到短期记忆
                self.memory_manager.add_to_short_term("用户", cleaned_input)
                
                # 检索相关记忆
                memory_context = self.memory_manager.retrieve_memories(cleaned_input)
                if memory_context == "无相关记忆。":
                    memory_context = ""
                
                # 开始思考时可以切换表情
                self.signals.expression_change.emit(Emotion.THINKING)
                
                # 在下一轮若需强制继续未完成任务，则把提示插入到用户输入前
                with self._force_lock:
                    should_force = self._force_continue_next
                    if should_force:
                        self._force_continue_next = False
                if should_force and cleaned_input and cleaned_input.lower() not in ('status','exit','quit'):
                    cleaned_input = "请继续执行未完成的任务，发送指令标签。\n\n" + cleaned_input

                # --- 注入记忆上下文（OpenManus 处理自己的浏览器状态）---
                full_memory_context = memory_context

                # 调用 LLM 生成响应
                ai_response = call_llm(SYSTEM_PROMPT, MODEL_NAME, cleaned_input, full_memory_context)
                skip_tts_for_response = False

                # --- 语义触发：优先检测是否包含 [SUMMON_AGENT] 标签 ---
                # 优先尝试完整的开闭标签
                summon_pattern = r'\[SUMMON_AGENT\](.*?)\[/SUMMON_AGENT\]'
                m = re.search(summon_pattern, ai_response, re.DOTALL)
                # 如果严格匹配失败但包含开始标签（LLM 经常漏写闭合标签），尝试宽松匹配
                if not m and '[SUMMON_AGENT]' in ai_response:
                    # LLM 经常用 markdown 代码围栏包裹 JSON，需要跳过 ```json ... ```
                    lenient_pattern = r'\[SUMMON_AGENT\]\s*(?:```\w*\s*)?(\{.*?\})\s*(?:```)?' 
                    m = re.search(lenient_pattern, ai_response, re.DOTALL)
                if m:
                    # 提取标签前的普通回复以及标签内的 JSON 任务
                    pre_text = ai_response[:m.start()].strip()
                    tag_json = m.group(1).strip()
                    # 清理 LLM 可能残留的 markdown 代码围栏标记
                    tag_json = re.sub(r'^```\w*\s*', '', tag_json)
                    tag_json = re.sub(r'\s*```\s*$', '', tag_json)
                    tag_json = tag_json.strip()
                    task_desc = None
                    try:
                        payload = json.loads(tag_json)
                        task_desc = payload.get('task')
                        # LLM 可能返回 {"action":...} / {"actions":...} / {"tool":...}
                        # 而不是标准的 {"task":"..."}，统一回退到用户原始输入
                        if not task_desc:
                            task_desc = cleaned_input
                            logger.info(f"SUMMON_AGENT JSON 无 task 字段(keys={list(payload.keys())})，使用用户原始输入作为任务: {task_desc}")
                        # 检测 task_desc 是否看起来像工具名称而不是完整查询
                        # 工具名称通常很短且简单（如 "search_web", "browser_use"）
                        # 完整查询应该包含中文、空格或较长的描述
                        elif task_desc and isinstance(task_desc, str):
                            # 如果 task 看起来像工具名（短字符串，仅包含字母、数字、下划线），则使用原始输入
                            if len(task_desc) < 20 and re.match(r'^[a-zA-Z0-9_]+$', task_desc):
                                logger.warning(f"SUMMON_AGENT JSON 中的 task 看起来是工具名称 '{task_desc}'，不是完整查询。使用用户原始输入: {cleaned_input}")
                                task_desc = cleaned_input
                    except Exception as e:
                        # JSON 解析失败时，用用户原始输入作为任务
                        logger.warning(f"解析 SUMMON_AGENT JSON 失败: {e}，使用用户输入作为 task")
                        task_desc = cleaned_input

                    # 先播放标签前的闲聊文本，如果没有则生成默认开始提示
                    if pre_text:
                        self.signals.speak_request.emit(pre_text)
                    else:
                        # 没有 pre_text 时，生成一个简短的开始执行提示
                        try:
                            start_prompt = """用户让你帮忙执行一个操作任务。
请用你的人设风格，只生成一句简短的确认语（5-10字），表示你开始执行了。
示例：好的，交给我吧~ / 没问题~ / 马上处理~ / 好嘞~
注意：不要提及具体任务内容，不要说"我来帮你"之类的长句子，只要简短确认即可。
只输出确认语，不要输出任何其他内容。"""
                            start_reply = call_llm(SYSTEM_PROMPT, MODEL_NAME, start_prompt, "")
                            # 清理回复，去掉可能的引号和多余内容
                            start_reply = start_reply.strip().strip('"\'')
                            if start_reply and len(start_reply) < 30:
                                self.signals.speak_request.emit(start_reply)
                            else:
                                self.signals.speak_request.emit("好的~")
                        except Exception as e:
                            logger.warning(f"生成任务开始语音失败: {e}")
                            self.signals.speak_request.emit("好的~")

                    clean_pre = pre_text if pre_text else ""

                    # 阻塞地调用 OpenManus Agent 执行任务（如果已初始化）
                    agent_result = "⚠️ Agent 未启用"
                    if self.agent and task_desc:
                        logger = get_logger('AIWorker')
                        logger.info(f"Invoking ManusAgent.run_task — task_desc={task_desc}")
                        try:
                            agent_result = self.agent.run_task(task_desc)
                            logger.info(f"ManusAgent.run_task completed — result(len)={len(agent_result) if isinstance(agent_result, str) else 'N/A'}")
                        except Exception as e:
                            logger.exception(f"ManusAgent.run_task raised exception: {e}")
                            agent_result = f"❌ Agent 执行异常: {e}"
                    elif task_desc:
                        agent_result = "⚠️ Agent 未初始化或不可用"

                    # 将 Agent 的执行结果显示在 UI 上
                    combined = (clean_pre + "\n\n[Agent 执行结果]\n" + agent_result).strip()

                    # 将结果作为最终响应发送并写入记忆
                    self.signals.expression_change.emit(combined)
                    self.signals.response_ready.emit(combined)
                    if combined != "抱歉，我现在有点卡住了。":
                        self.memory_manager.add_to_short_term("AI", combined)
                        self.memory_manager.store_memory(f"用户: {cleaned_input}\nAI: {combined}")

                    # 任务完成后，调用 LLM 生成符合人设的简短语音回复
                    try:
                        # 判断任务是否成功
                        is_success = "success" in agent_result.lower() or "完成" in agent_result or "成功" in agent_result
                        is_failure = "failure" in agent_result.lower() or "失败" in agent_result or "异常" in agent_result or "错误" in agent_result
                        
                        if is_success:
                            summary_prompt = """你刚刚帮用户完成了一个操作任务，任务成功了。
请用你的人设风格，生成一句简短的完成确认语（5-15字）。
示例：搞定啦~ / 完成了哦~ / 好了~ / 已经弄好了~
注意：不要提及具体任务内容，不要说复杂的话，只要简短确认完成即可。
只输出确认语，不要输出任何其他内容。"""
                        elif is_failure:
                            summary_prompt = """你刚刚帮用户执行一个操作任务，但是遇到了一些问题。
请用你的人设风格，生成一句简短的抱歉语（5-15字）。
示例：抱歉，没成功呢... / 出了点问题~ / 失败了，下次再试吧~
注意：不要提及具体错误内容，不要说复杂的话，只要简短表达歉意即可。
只输出抱歉语，不要输出任何其他内容。"""
                        else:
                            summary_prompt = """你刚刚帮用户处理了一个操作任务。
请用你的人设风格，生成一句简短的完成确认语（5-15字）。
示例：处理好了~ / 弄完了哦~ / 搞定~
注意：不要提及具体任务内容，只要简短确认即可。
只输出确认语，不要输出任何其他内容。"""
                        
                        voice_reply = call_llm(SYSTEM_PROMPT, MODEL_NAME, summary_prompt, "")
                        
                        # 清理回复，去掉引号和多余内容
                        voice_reply = voice_reply.strip().strip('"\'')
                        if voice_reply and len(voice_reply) < 50:
                            self.signals.speak_request.emit(voice_reply)
                            logger.info(f"Agent 任务完成语音回复: {voice_reply}")
                        else:
                            # 回复太长，使用默认
                            default_reply = "搞定啦~" if is_success else ("抱歉没成功呢..." if is_failure else "处理好了~")
                            self.signals.speak_request.emit(default_reply)
                    except Exception as e:
                        logger.warning(f"生成任务完成语音回复失败: {e}")
                        self.signals.speak_request.emit("好了~")

                    # 本次循环结束，等待下一个用户输入
                    continue

                # --- 自动检测：LLM 直接输出包含工具调用意图时，交由 Agent 处理 ---
                try:
                    parsed_agent = extract_first_json(ai_response)
                    if parsed_agent and isinstance(parsed_agent, dict) and 'tool' in parsed_agent:
                        # LLM 直接输出了工具调用 JSON，将原始用户请求交由 Agent 执行
                        logger.info("检测到 LLM 直接输出工具调用 JSON，转交 Agent 处理")
                        if self.agent:
                            agent_result = self.agent.run_task(cleaned_input)
                            ai_response = agent_result
                            skip_tts_for_response = True
                            
                            # 生成符合人设的语音回复
                            try:
                                is_success = "success" in agent_result.lower() or "完成" in agent_result or "成功" in agent_result
                                is_failure = "failure" in agent_result.lower() or "失败" in agent_result or "异常" in agent_result
                                
                                if is_success:
                                    summary_prompt = """你刚刚帮用户完成了一个操作任务，任务成功了。
请用你的人设风格，生成一句简短的完成确认语（5-15字）。
示例：搞定啦~ / 完成了哦~ / 好了~
注意：不要提及具体任务内容，只要简短确认完成即可。
只输出确认语，不要输出任何其他内容。"""
                                elif is_failure:
                                    summary_prompt = """你刚刚帮用户执行一个操作任务，但是遇到了一些问题。
请用你的人设风格，生成一句简短的抱歉语（5-15字）。
示例：抱歉，没成功呢... / 出了点问题~
注意：不要提及具体错误内容，只要简短表达歉意即可。
只输出抱歉语，不要输出任何其他内容。"""
                                else:
                                    summary_prompt = """你刚刚帮用户处理了一个操作任务。
请用你的人设风格，生成一句简短的完成确认语（5-15字）。
示例：处理好了~ / 弄完了哦~
只输出确认语，不要输出任何其他内容。"""
                                
                                voice_reply = call_llm(SYSTEM_PROMPT, MODEL_NAME, summary_prompt, "")
                                voice_reply = voice_reply.strip().strip('"\'')
                                if voice_reply and len(voice_reply) < 50:
                                    self.signals.speak_request.emit(voice_reply)
                                    logger.info(f"Agent 任务完成语音回复: {voice_reply}")
                                else:
                                    default_reply = "搞定啦~" if is_success else ("抱歉没成功呢..." if is_failure else "处理好了~")
                                    self.signals.speak_request.emit(default_reply)
                            except Exception as ve:
                                logger.warning(f"生成任务完成语音回复失败: {ve}")
                                self.signals.speak_request.emit("好了~")
                        else:
                            logger.warning("Agent 未初始化，无法处理工具调用")
                except Exception as e:
                    logger.error(f"自动 Agent 检测失败: {e}", exc_info=True)

                # 常规文本响应处理
                clean_response = ai_response

                # 根据响应内容自动切换表情
                self.signals.expression_change.emit(clean_response)  # 发送文本，让主线程分析情感

                # 发送响应到主线程
                self.signals.response_ready.emit(clean_response)


                # 处理记忆
                if clean_response != "抱歉，我现在有点卡住了。":
                    self.memory_manager.add_to_short_term("AI", clean_response)
                    self.memory_manager.store_memory(f"用户: {cleaned_input}\nAI: {clean_response}")
                
                # 语音合成（请求主线程进行口型同步）
                if not skip_tts_for_response:
                    self.signals.speak_request.emit(clean_response)
                
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
    
    def stop(self):
        """停止线程"""
        self._running = False


class MainApplication:
    """
    主应用程序类
    管理 PyQt 应用、Avatar 窗口和 AI 工作线程
    """
    
    def __init__(self):
        self.app: Optional[QApplication] = None
        self.avatar: Optional[AvatarWidget] = None
        self.ai_worker: Optional[AIWorker] = None
        self.ear_worker: Optional[EarWorker] = None
        self.input_queue: queue.Queue = queue.Queue()
        self.signals: Optional[AIWorkerSignals] = None
        
        self.memory_manager: Optional[MemoryManager] = None
        self.voice_manager: Optional[VoiceManager] = None

        self.sovits_process = None
        self.agent: Optional[ManusAgent] = None  # 本地智能体（ManusAgent）实例
        
        # 口型同步和表情管理器
        self.lip_sync_manager: Optional[LipSyncManager] = None
        self.expression_manager: Optional[ExpressionManager] = None
        
        # 用于控制输入提示符的事件
        self.can_input = threading.Event()
        self.can_input.set()  # 初始化为可输入状态
    
    def setup(self):
        """初始化所有组件"""
        logger = get_logger('MainApplication')
        
        # 创建 PyQt 应用（必须最先创建）
        self.app = QApplication(sys.argv)
        
        # 创建信号对象
        self.signals = AIWorkerSignals()
        self._connect_signals()
        
        # 启动 GPT-SoVITS 服务
        self.sovits_process = start_gpt_sovits_api(GPT_SOVITS_PATH)
        if self.sovits_process is None:
            logger.warning("GPT-SoVITS API 服务启动失败。")
        
        # 初始化模块
        self.memory_manager = MemoryManager()
        self.voice_manager = VoiceManager(
            sovits_url=SOVITS_URL,
            ref_audio=REF_AUDIO,
            prompt_text=PROMPT_TEXT,
        )
        
        # 初始化 Agent（基于 OpenManus 框架的智能体）
        self.agent = ManusAgent(
            system_prompt=SYSTEM_PROMPT,
            max_steps=100,
        )
        logger.info("OpenManus 智能体已初始化")

        
        # 清理旧记忆
        self.memory_manager.cleanup_old_memories()
        
        # 创建 Avatar 窗口
        self.avatar = AvatarWidget(
            width=400,
            height=600,
            x=100,
            y=100
        )
        
        # 初始化口型同步管理器（通过信号更新，保证线程安全）
        self.lip_sync_manager = LipSyncManager(
            update_callback=lambda v: self.signals.lip_sync_update.emit(v)
        )
        
        # 初始化表情管理器
        self.expression_manager = ExpressionManager(
            expression_callback=self._change_expression,
            motion_callback=self._play_motion
        )
        
        # 启动 AI 工作线程
        self.ai_worker = AIWorker(
            signals=self.signals,
            input_queue=self.input_queue,
            memory_manager=self.memory_manager,
            voice_manager=self.voice_manager,
            agent=self.agent
        )
    
    def _connect_signals(self):
        """连接信号与槽"""
        self.signals.response_ready.connect(self._on_response_ready)
        self.signals.lip_sync_update.connect(self._on_lip_sync_update)
        self.signals.expression_change.connect(self._on_expression_change)
        self.signals.motion_play.connect(self._on_motion_play)
        self.signals.status_update.connect(self._on_status_update)
        self.signals.shutdown.connect(self._on_shutdown)
        self.signals.speak_request.connect(self._on_speak_request)
        self.signals.play_audio.connect(self._on_play_audio)
        self.signals.ear_recognized.connect(self._on_ear_recognized)
    
    def _change_expression(self, expression_index: int):
        """表情切换回调 - 被 ExpressionManager 调用"""
        if self.avatar:
            self.avatar.change_expression(expression_index)
    
    def _play_motion(self, group: str, index: int):
        """播放动作回调 - 被 ExpressionManager 调用"""
        if self.avatar:
            self.avatar.play_motion(group, index)
    
    def _on_response_ready(self, response: str):
        """处理 AI 响应"""
        logger = get_logger('MainApplication')
        logger.info(f"AI: {response}")
        # 响应完成，允许下一次输入
        self.can_input.set()
    
    def _on_lip_sync_update(self, value: float):
        """更新口型（直接信号调用）"""
        if self.avatar:
            self.avatar.update_lip_sync(value)
    
    def _on_expression_change(self, expression):
        """切换表情 - 接收 Emotion 枚举或文本字符串"""
        if self.expression_manager:
            if isinstance(expression, Emotion):
                # 直接设置情感
                self.expression_manager.set_emotion(expression)
            elif isinstance(expression, str):
                # 分析文本内容的情感
                self.expression_manager.set_expression_from_text(expression)
    
    def _on_motion_play(self, group: str, index: int):
        """播放动作"""
        if self.avatar:
            self.avatar.play_motion(group, index)
    
    def _on_speak_request(self, text: str):
        """处理语音合成请求 - 浏览器内音频播放和口型同步（100%完美同步）

        如果传入的文本包含 Agent-style 的 JSON（例如 {"thought":...,"tool":...}），
        则语音只朗读 JSON 中的 `thought` 字段，界面仍然显示原始文本。
        """
        logger = get_logger('MainApplication')

        # 优先尝试从可能的 JSON 中抽取 `thought` 字段，仅将其送入 TTS
        speak_text = text
        try:
            m = re.search(r'(\{(?:.|\n)*?\})', text)
            if m:
                try:
                    candidate = json.loads(m.group(1))
                    if isinstance(candidate, dict) and 'thought' in candidate and isinstance(candidate['thought'], str):
                        speak_text = candidate['thought']
                except Exception:
                    # 忽略解析错误，回退为原始文本
                    pass
        except Exception:
            pass

        # 过滤表情标签，避免在语音中读出
        filtered_text = filter_emotion_tags(speak_text)
        logger.debug(f"[TTS] 收到语音请求(用于朗读): {filtered_text[:50]}...")

        if self.voice_manager and self.avatar:
            try:
                # 生成临时 wav 文件路径
                wav_path = os.path.join(
                    os.path.dirname(__file__), 
                    'data', 'temp', 
                    f'tts_{int(time.time() * 1000)}.wav'
                )
                os.makedirs(os.path.dirname(wav_path), exist_ok=True)
                logger.debug(f"[TTS] wav 保存路径: {wav_path}")

                # 在子线程中执行 TTS（避免阻塞主线程）
                def speak_with_browser():
                    try:
                        logger.debug("[TTS] 开始合成语音...")

                        # 1. 合成语音并保存到本地
                        if not self.voice_manager.speak_and_save(filtered_text, wav_path):
                            logger.warning("[TTS] 语音合成失败")
                            return

                        logger.debug(f"[TTS] 语音合成成功, 文件存在: {os.path.exists(wav_path)}")

                        # 2. 通过信号让主线程播放音频
                        logger.debug("[TTS] 发送 play_audio 信号...")
                        self.signals.play_audio.emit(wav_path)

                        # 3. 等待音频时长后清理临时文件
                        try:
                            with wave.open(wav_path, 'rb') as wf:
                                frames = wf.getnframes()
                                rate = wf.getframerate()
                                duration = frames / float(rate)

                            logger.debug(f"[TTS] 音频时长: {duration:.2f}秒")

                            # 等待播放完成后清理
                            time.sleep(duration + 0.5)
                            try:
                                os.remove(wav_path)
                                logger.debug("[TTS] 临时文件已清理")
                            except:
                                pass
                        except Exception as e:
                            logger.warning(f"[TTS] 读取 wav 错误: {e}")

                    except Exception as e:
                        logger.error(f"[TTS] 错误: {e}", exc_info=True)

                # 启动子线程执行
                threading.Thread(target=speak_with_browser, daemon=True).start()

            except Exception as e:
                logger.error(f"[TTS] 错误: {e}", exc_info=True)
        else:
            logger.warning(f"[TTS] voice_manager={self.voice_manager}, avatar={self.avatar}")
    
    def _on_play_audio(self, wav_path: str):
        """在主线程中播放音频（由信号触发）"""
        logger = get_logger('MainApplication')
        logger.debug(f"[TTS] 主线程收到播放请求: {wav_path}")
        if self.avatar:
            self.avatar.play_audio(wav_path)
    
    def _on_status_update(self, status: str):
        """显示状态"""
        logger = get_logger('MainApplication')
        logger.info(f"📊 {status}")
    
    def _on_ear_recognized(self, text: str):
        """处理 Ear 模块识别的文本"""
        logger = get_logger('MainApplication')
        logger.info(f"👂 Ear 识别: {text}")
        # Ear 已将文本放入 input_queue，AIWorker 会自动处理
    
    def _on_shutdown(self):
        """处理关闭信号"""
        self.cleanup()
        self.app.quit()
    
    def cleanup(self):
        """清理资源"""
        logger = get_logger('MainApplication')
        
        # 停止口型同步
        if self.lip_sync_manager:
            self.lip_sync_manager.stop()
        
        # 停止 Ear 工作线程
        if self.ear_worker:
            self.ear_worker.stop()
        
        # 停止 AI 工作线程
        if self.ai_worker:
            self.ai_worker.stop()
            self.input_queue.put(None)  # 发送退出信号
        
        # 保存记忆
        if self.memory_manager:
            self.memory_manager.summarize_day()
            self.memory_manager.close()
        
        # 清理 Agent 资源（关闭 OpenManus 事件循环等）
        if self.agent:
            self.agent.cleanup()
        
        # 停止语音服务
        if self.sovits_process:
            self.sovits_process.terminate()
            self.sovits_process.wait()
            logger.info("GPT-SoVITS API 服务已停止。")
    
    def run(self):
        """运行应用程序"""
        logger = get_logger('MainApplication')
        
        # 显示 Avatar 窗口
        self.avatar.show()
        
        # 延迟加载模型（等待页面加载完成）
        QTimer.singleShot(1500, self._load_default_model)
        
        # 启动 Ear 工作线程（麦克风监听）
        logger.info("🎤 正在启动 Ear 听觉模块...")
        self.ear_worker = EarWorker(self.input_queue, model_size="base")
        self.ear_worker.start()
        
        # 启动 AI 工作线程
        self.ai_worker.start()
        
        # 显示启动信息（单行输出，避免日志混乱）
        stats = self.memory_manager.get_memory_stats()
        logger = get_logger('MainApplication')
        logger.info(f"🤖  Project Local 已启动（带 Avatar 模块）")
        logger.info("💬  现在可以直接输入文字进行对话，或通过麦克风说话！")
        logger.info("输入 'exit' 或 'quit' 退出，输入 'status' 查看记忆状态。")
        
        # 启动控制台输入线程（在启动信息之后）
        console_thread = threading.Thread(target=self._console_input_loop, daemon=True)
        console_thread.start()
        
        # 运行 Qt 事件循环（阻塞）
        return self.app.exec()
    
    def _load_default_model(self):
        """加载默认模型"""
        # 示例：如果 models 目录下有模型，自动加载第一个
        from pathlib import Path
        models_dir = Path(__file__).parent / "assets" / "web" / "models"
        if models_dir.exists():
            for model_file in models_dir.rglob("*.model3.json"):
                avatar_log_info(f"Found model: {model_file}")
                self.avatar.load_model(str(model_file))
                break
            else:
                for model_file in models_dir.rglob("*.model.json"):
                    avatar_log_info(f"Found model: {model_file}")
                    self.avatar.load_model(str(model_file))
                    break
                else:
                    avatar_log_info("No model found in models directory")
    
    def _console_input_loop(self):
        """控制台输入循环（在子线程运行）"""
        # 等待一小段时间，确保启动信息打印完成
        time.sleep(0.5)
        
        while True:
            try:
                # 等待允许输入
                self.can_input.wait()
                
                user_input = input("")
                
                # 设置为不可输入状态，直到 AI 响应完成
                if user_input.strip():
                    self.can_input.clear()
                
                self.input_queue.put(user_input)
                
                if user_input.lower() in ['exit', 'quit']:
                    break
            except EOFError:
                break
            except Exception as e:
                pass  # 忽略输入错误





def signal_handler(sig, frame):
    """处理 Ctrl+C 信号"""
    print("\n正在退出...")
    sys.exit(0)


def main():
    """主入口"""
    # 初始化日志系统
    logger = get_logger('ProjectLocal')
    logger.info("启动 Project Local...")
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 创建并运行应用
    app = MainApplication()
    app.setup()
    
    try:
        sys.exit(app.run())
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在清理资源...")
        app.cleanup()
        sys.exit(0)


if __name__ == "__main__":
    import sys
    # 支持命令行参数：
    #   --ear-demo     启动听觉模块演示（原有代码）

    # 提供一个可选的命令行参数: --ear-demo ，用于快速本地测试 modules/ear.py 的听觉功能 - 暂时禁用
    # if "--ear-demo" in sys.argv:
    #     print("[main] 启动 Ear 模块演示 (--ear-demo)。按 Ctrl+C 退出。")
    #     from modules.ear import Ear
    #     ear = Ear(model_size="base")
    #     try:
    #         ear.listen(callback=lambda txt: print("[EAR DEMO] 识别:", txt))
    #     finally:
    #         ear.close()
    #         sys.exit(0)

    main()
