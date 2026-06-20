"""
语音识别工作线程 —— PyAudio 录音 + Faster-Whisper 转写。
模型必须在主线程加载后传入（macOS CTranslate2 限制）。
采用按钮控制监听：开始监听后转写语音，GUI 负责唤醒词与命令流程。
"""

import time
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


class SpeechWorker(QThread):
    """语音识别线程 — 负责录音、转写，模型由外部加载后注入"""

    # ---- 信号 ----
    status_changed = pyqtSignal(str)       # 状态文本
    transcription_ready = pyqtSignal(str)  # 识别结果文本
    error_occurred = pyqtSignal(str)       # 错误信息

    def __init__(self, whisper_model=None):
        """
        Args:
            whisper_model: 已加载的 Faster-Whisper WhisperModel 实例（必须在主线程创建）
        """
        super().__init__()
        self.model = whisper_model
        self._command = "idle"
        self._running = True
        self._audio_buffer = []

    # ================================================================
    # 公开接口（主线程调用）
    # ================================================================

    def start_recording(self):
        self._command = "start_record"

    def stop_recording(self):
        self._command = "stop_record"

    def stop(self):
        self._running = False
        self._command = "quit"

    @property
    def is_ready(self):
        return self.model is not None

    # ================================================================
    # 内部逻辑（在工作线程中执行）
    # ================================================================

    def _open_mic(self):
        """打开 PyAudio 麦克风流"""
        try:
            import pyaudio
        except ImportError:
            self.error_occurred.emit("PyAudio 未安装，请执行: pip install pyaudio")
            return None, None

        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
            )
            return p, stream
        except Exception as e:
            self.error_occurred.emit(f"无法打开麦克风: {e}")
            return None, None

    def _transcribe(self, audio_bytes: bytes) -> str:
        """调用 Faster-Whisper 转写音频"""
        if not self.model or len(audio_bytes) < 1600:
            return ""

        audio_np = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )

        segments, _info = self.model.transcribe(
            audio_np,
            language="zh",
            beam_size=5,
            vad_filter=True,
        )

        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
        return " ".join(parts)

    # ================================================================
    # 线程主循环
    # ================================================================

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"语音线程异常: {e}\n{traceback.format_exc()}")
            self.status_changed.emit("❌ 语音线程崩溃")

    def _run_impl(self):
        if not self.model:
            self.error_occurred.emit("语音模型未加载")
            return

        # --- 预打开音频设备验证可用 ---
        p, _stream = self._open_mic()
        if p is None:
            return
        # 立即关闭测试流，后续录音时再重新打开
        if _stream:
            try:
                _stream.stop_stream()
                _stream.close()
            except Exception:
                pass

        self.status_changed.emit("✅ 语音模型就绪 — 点击开始监听")

        stream = None
        is_recording = False

        # --- 主循环 ---
        while self._running:
            cmd = self._command

            # ---- 开始录音 ----
            if cmd == "start_record" and not is_recording:
                self._audio_buffer = []
                is_recording = True
                self._command = "recording"
                self.status_changed.emit("🔴 正在监听...")

                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                try:
                    stream = p.open(
                        format=8,             # paInt16
                        channels=1,
                        rate=16000,
                        input=True,
                        frames_per_buffer=1024,
                    )
                except Exception as e:
                    self.error_occurred.emit(f"麦克风打开失败: {e}")
                    is_recording = False
                    self._command = "idle"
                    continue

            # ---- 停止录音并转写 ----
            elif cmd == "stop_record" and is_recording:
                self._command = "transcribing"
                is_recording = False

                if stream:
                    try:
                        for _ in range(5):
                            data = stream.read(1024, exception_on_overflow=False)
                            self._audio_buffer.append(data)
                    except Exception:
                        pass
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                    stream = None

                if self._audio_buffer:
                    self.status_changed.emit("⏳ 正在识别...")
                    try:
                        raw_bytes = b"".join(self._audio_buffer)
                        text = self._transcribe(raw_bytes)
                        if text:
                            self.transcription_ready.emit(text)
                            self.status_changed.emit("✅ 识别完成 — 点击开始监听")
                        else:
                            self.status_changed.emit("⚠️ 未识别到语音 — 请重试")
                    except Exception as e:
                        self.error_occurred.emit(f"识别失败: {e}")
                        self.status_changed.emit("❌ 识别失败 — 请重试")
                else:
                    self.status_changed.emit("⚠️ 未录制到音频 — 请重试")

                self._audio_buffer = []
                self._command = "idle"

            # ---- 录音中：持续读取音频 ----
            elif is_recording and stream is not None:
                try:
                    data = stream.read(1024, exception_on_overflow=False)
                    self._audio_buffer.append(data)
                except Exception as e:
                    self.error_occurred.emit(f"录音错误: {e}")

            # ---- 空闲 ----
            else:
                time.sleep(0.05)

        # --- 清理 ---
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if p:
            try:
                p.terminate()
            except Exception:
                pass
