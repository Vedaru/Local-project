# voice.py - 语音模块（低延迟版）

import requests
import pyaudio
import threading
import queue
import time

class VoiceManager:
    def __init__(self, sovits_url="http://127.0.0.1:9880", ref_audio="", prompt_text=""):
        self.sovits_url = sovits_url
        self.ref_audio = ref_audio
        self.prompt_text = prompt_text
        self.text_queue = queue.Queue()
        self.audio_queue = queue.Queue()
        self.session = requests.Session()
        
        # 低延迟音频配置
        self.sample_rate = 32000
        self.chunk_size = 256  # 更小的chunk降低延迟
        
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=self.chunk_size  # 匹配chunk大小
        )
        
        # 播放状态控制
        self.is_playing = False
        self.stop_current = threading.Event()

        # 启动工作线程
        threading.Thread(target=self.tts_worker, daemon=True).start()
        threading.Thread(target=self.playback_worker, daemon=True).start()

        # 预热 TTS，减少首句延迟
        threading.Thread(target=self._warmup_tts, daemon=True).start()

    def speak(self, text):
        """发送文本到TTS队列"""
        # 如果正在播放，可以选择打断
        self.text_queue.put(text)

    def _warmup_tts(self):
        """预热 TTS 服务，触发模型与连接初始化"""
        try:
            tts_data = {
                "text": "你好",
                "text_lang": "zh",
                "ref_audio_path": self.ref_audio,
                "prompt_lang": "zh",
                "prompt_text": self.prompt_text,
                "text_split_method": "cut5",
                "media_type": "raw",
                "streaming_mode": True,
                "parallel_infer": True,
                "speed_factor": 1.0,
            }
            with self.session.post(
                f"{self.sovits_url}/tts",
                json=tts_data,
                stream=True,
                timeout=(2, 10)
            ) as resp:
                resp.raise_for_status()
                for _ in resp.iter_content(chunk_size=512):
                    break
        except Exception:
            pass

    def interrupt(self):
        """打断当前播放"""
        self.stop_current.set()
        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

    def tts_worker(self):
        """TTS请求线程 - 流式获取音频数据"""
        while True:
            text = self.text_queue.get()
            if text is None:
                break
            
            self.stop_current.clear()
            self.is_playing = True
            
            try:
                tts_data = {
                    "text": text,
                    "text_lang": "zh",
                    "ref_audio_path": self.ref_audio,
                    "prompt_lang": "zh",
                    "prompt_text": self.prompt_text,
                    "text_split_method": "cut5",
                    "media_type": "raw",
                    "streaming_mode": True,  # 确保流式模式
                    "parallel_infer": True,
                    "speed_factor": 1.0
                }
                
                # 使用更小的chunk和更短的超时
                with self.session.post(
                    f"{self.sovits_url}/tts",
                    json=tts_data,
                    stream=True,
                    timeout=(2, 20)  # (连接超时, 读取超时)
                ) as resp:
                    resp.raise_for_status()

                    # 通知播放线程新流开始，首包即播
                    self.audio_queue.put(b'__START__')
                    
                    # 使用更小的chunk_size实现更低延迟
                    for chunk in resp.iter_content(chunk_size=512):
                        if self.stop_current.is_set():
                            break
                        if chunk:
                            self.audio_queue.put(chunk)
                            
            except requests.exceptions.RequestException as e:
                print(f"[TTS网络错误] {e}")
            except Exception as e:
                print(f"[TTS错误] {e}")
            finally:
                # 发送结束标记
                self.audio_queue.put(b'__END__')
                self.text_queue.task_done()

    def playback_worker(self):
        """音频播放线程 - 低延迟播放"""
        buffer = b''
        min_buffer_size = 256  # 最小缓冲大小，收到这么多数据就开始播放
        immediate_first_packet = False
        
        while True:
            try:
                # 非阻塞获取，超时后检查buffer
                chunk = self.audio_queue.get(timeout=0.01)
                
                if chunk is None:
                    break
                
                if chunk == b'__END__':
                    # 播放剩余buffer
                    if buffer:
                        self.stream.write(buffer)
                        buffer = b''
                    self.is_playing = False
                    self.audio_queue.task_done()
                    continue

                if chunk == b'__START__':
                    buffer = b''
                    immediate_first_packet = True
                    self.audio_queue.task_done()
                    continue
                
                if immediate_first_packet:
                    self.stream.write(chunk)
                    immediate_first_packet = False
                elif len(chunk) >= min_buffer_size:
                    self.stream.write(chunk)
                else:
                    buffer += chunk

                # 达到最小缓冲就开始播放
                while len(buffer) >= min_buffer_size:
                    self.stream.write(buffer[:min_buffer_size])
                    buffer = buffer[min_buffer_size:]
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                # 队列为空时，播放剩余buffer（如果有）
                if buffer and len(buffer) >= 128:
                    write_size = min(len(buffer), min_buffer_size)
                    self.stream.write(buffer[:write_size])
                    buffer = buffer[write_size:]
                continue

    def close(self):
        """关闭语音管理器"""
        self.text_queue.put(None)
        self.audio_queue.put(None)
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()