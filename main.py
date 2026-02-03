"""
Project Local - 带 Avatar 虚拟形象的主入口文件
演示如何将 PyQt6 GUI 与 AI 逻辑在不同线程中集成
"""
import signal
import sys
import os

# 必须在导入任何其他模块前设置环境变量（修复 ctranslate2 的 ROCm 路径问题）
os.environ["CT2_USE_CUDA"] = "0"

import threading
import queue
import tempfile
import time
from typing import Optional

from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from modules.avatar import AvatarWidget, AvatarManager
from modules.avatar import LipSyncManager, ExpressionManager, Emotion
from modules.avatar.logger import log_info as avatar_log_info
from modules.memory import MemoryManager
from modules.memory.logger import get_logger as get_memory_logger
from modules.voice import VoiceManager
from modules.ear import Ear
from modules.llm import call_llm
from modules.config import REF_AUDIO, PROMPT_TEXT, SOVITS_URL, GPT_SOVITS_PATH, MODEL_NAME, SYSTEM_PROMPT
from modules.utils import clean_text, start_gpt_sovits_api, check_sovits_service
from modules.logging_config import get_logger


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
    """
    
    def __init__(self, input_queue: queue.Queue, model_size: str = "base"):
        super().__init__(daemon=True)
        self.input_queue = input_queue
        self.model_size = model_size
        self.ear = None
        self._running = True
    
    def run(self):
        """线程主循环"""
        logger = get_logger('EarWorker')
        try:
            logger.info(f"[Ear] 初始化听觉模块，模型大小: {self.model_size}")
            self.ear = Ear(model_size=self.model_size)
            
            def on_text_recognized(text: str):
                """当识别到文本时，发送到 AIWorker 的输入队列"""
                if self._running and text.strip():
                    logger.info(f"[Ear] 识别结果: {text}")
                    self.input_queue.put(text)
            
            # 开始阻塞监听麦克风
            logger.info("[Ear] 开始监听麦克风...")
            self.ear.listen(callback=on_text_recognized)
            
        except Exception as e:
            logger.error(f"[Ear] 错误: {e}", exc_info=True)
        finally:
            if self.ear:
                self.ear.close()
            logger.info("[Ear] 听觉模块已关闭")
    
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
        voice_manager: VoiceManager
    ):
        super().__init__(daemon=True)
        self.signals = signals
        self.input_queue = input_queue
        self.memory_manager = memory_manager
        self.voice_manager = voice_manager
        self._running = True
    
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
                        f"  ├─ 短期记忆: {stats['short_term']}/{stats['short_term_capacity']} 轮\n"
                        f"  ├─ 工作记忆: {stats['working_memory']} 条\n"
                        f"  ├─ 长期记忆: {stats['long_term']} 条\n"
                        f"  ├─ 情感记忆: {stats['emotional']} 条\n"
                        f"  └─ 当前情感: {stats['current_emotion']}"
                    )
                    self.signals.status_update.emit(status_msg)
                    continue
                
                # 清理输入文本
                cleaned_input = clean_text(user_input)
                
                # 跳过空输入
                if not cleaned_input.strip():
                    continue
                
                # 添加到短期记忆
                self.memory_manager.add_to_short_term("用户", cleaned_input)
                
                # 检索相关记忆
                memory_context = self.memory_manager.retrieve_memories(cleaned_input)
                if memory_context == "无相关记忆。":
                    memory_context = ""
                
                # 开始思考时可以切换表情
                self.signals.expression_change.emit(Emotion.THINKING)
                
                # 调用 LLM 生成响应
                ai_response = call_llm(SYSTEM_PROMPT, MODEL_NAME, cleaned_input, memory_context)
                
                # 根据响应内容自动切换表情
                self.signals.expression_change.emit(ai_response)  # 发送文本，让主线程分析情感
                
                # 发送响应到主线程
                self.signals.response_ready.emit(ai_response)
                
                # 处理记忆
                if ai_response != "抱歉，我现在有点卡住了。":
                    self.memory_manager.add_to_short_term("AI", ai_response)
                    self.memory_manager.store_memory(f"用户: {cleaned_input}\nAI: {ai_response}")
                
                # 语音合成（请求主线程进行口型同步）
                self.signals.speak_request.emit(ai_response)
                
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
        self.ear_worker: Optional[EarWorker] = None  # 新增：Ear 工作线程
        self.input_queue: queue.Queue = queue.Queue()
        self.signals: Optional[AIWorkerSignals] = None
        
        self.memory_manager: Optional[MemoryManager] = None
        self.voice_manager: Optional[VoiceManager] = None
        self.sovits_process = None
        
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
            voice_manager=self.voice_manager
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
        """处理语音合成请求 - 浏览器内音频播放和口型同步（100%完美同步）"""
        logger = get_logger('MainApplication')
        logger.debug(f"[TTS] 收到语音请求: {text[:50]}...")
        
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
                        if not self.voice_manager.speak_and_save(text, wav_path):
                            logger.warning("[TTS] 语音合成失败")
                            return
                        
                        logger.debug(f"[TTS] 语音合成成功, 文件存在: {os.path.exists(wav_path)}")
                        
                        # 2. 通过信号让主线程播放音频
                        logger.debug("[TTS] 发送 play_audio 信号...")
                        self.signals.play_audio.emit(wav_path)
                        
                        # 3. 等待音频时长后清理临时文件
                        import wave
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
        print(status)
    
    def _on_ear_recognized(self, text: str):
        """处理 Ear 模块识别的文本"""
        logger = get_logger('MainApplication')
        logger.info(f"[Ear 识别] {text}")
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
        logger.info("正在启动 Ear 听觉模块...")
        self.ear_worker = EarWorker(self.input_queue, model_size="base")
        self.ear_worker.start()
        
        # 启动 AI 工作线程
        self.ai_worker.start()
        
        # 显示启动信息
        stats = self.memory_manager.get_memory_stats()
        logger.info("=" * 60)
        logger.info("Project Local 已启动（带 Avatar 和 Ear 听觉模块）。")
        logger.info(f"记忆状态: 短期({stats['short_term']}/{stats['short_term_capacity']}) | "
                   f"长期({stats['long_term']}) | 情感({stats['emotional']})")
        logger.info("📣 现在可以直接对麦克风说话！")
        logger.info("输入 'exit' 或 'quit' 退出，输入 'status' 查看记忆状态。")
        logger.info("=" * 60)
        
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
        import time
        # 等待一小段时间，确保启动信息打印完成
        time.sleep(0.5)
        
        while True:
            try:
                # 等待允许输入
                self.can_input.wait()
                
                user_input = input("你: ")
                
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
    # 提供一个可选的命令行参数: --ear-demo ，用于快速本地测试 modules/ear.py 的听觉功能
    if "--ear-demo" in sys.argv:
        print("[main] 启动 Ear 模块演示 (--ear-demo)。按 Ctrl+C 退出。")
        from modules.ear import Ear
        ear = Ear(model_size="base")
        try:
            ear.listen(callback=lambda txt: print("[EAR DEMO] 识别:", txt))
        finally:
            ear.close()
            sys.exit(0)

    main()
