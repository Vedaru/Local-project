# voice.py - 语音模块

import requests
import pyaudio
import threading
import queue

class VoiceManager:
    def __init__(self, sovits_url="http://127.0.0.1:9880", ref_audio="", prompt_text=""):
        self.sovits_url = sovits_url
        self.ref_audio = ref_audio
        self.prompt_text = prompt_text
        self.text_queue = queue.Queue()
        self.audio_queue = queue.Queue()
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=32000, output=True, frames_per_buffer=1024)

        # 启动工作线程
        threading.Thread(target=self.tts_worker, daemon=True).start()
        threading.Thread(target=self.playback_worker, daemon=True).start()

    def speak(self, text):
        self.text_queue.put(text)

    def tts_worker(self):
        while True:
            text = self.text_queue.get()
            if text is None:
                break
            try:
                tts_data = {
                    "text": text,
                    "text_lang": "zh",
                    "ref_audio_path": self.ref_audio,
                    "prompt_lang": "zh",
                    "prompt_text": self.prompt_text,
                    "text_split_method": "cut5",
                    "media_type": "raw",
                    "streaming_mode": 1,
                    "parallel_infer": True
                }
                with requests.post(f"{self.sovits_url}/tts", json=tts_data, stream=True, timeout=30) as resp:
                    resp.raise_for_status()  # 确保响应状态正确
                    for chunk in resp.iter_content(chunk_size=2048):
                        if chunk:
                            self.audio_queue.put(chunk)
            except requests.exceptions.RequestException as e:
                print(f"[TTS网络错误] {e}")
            except Exception as e:
                print(f"[TTS错误] {e}")
            self.text_queue.task_done()

    def playback_worker(self):
        while True:
            chunk = self.audio_queue.get()
            if chunk is None:
                break
            self.stream.write(chunk)
            self.audio_queue.task_done()

    def close(self):
        self.text_queue.put(None)
        self.audio_queue.put(None)
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()