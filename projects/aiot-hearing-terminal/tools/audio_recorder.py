"""
PC 端麦克风录音工具（开发期测试用）。

依赖：
    pip install pyaudio
    (Windows 装不上可用预编译 wheel: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio)

用法：
    from tools.audio_recorder import AudioRecorder
    rec = AudioRecorder()
    rec.record(duration=5, output_path="test.wav")
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Union


class AudioRecorder:
    """简单的麦克风录音器，输出 WAV 文件。"""

    def __init__(self, sample_rate: int = 16000, channels: int = 1, chunk: int = 1024):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk = chunk

    def record(self, duration: float, output_path: Union[str, Path]) -> bool:
        """录制 duration 秒并保存为 WAV。成功返回 True。"""
        try:
            import pyaudio
        except ImportError:
            print("[AudioRecorder] 需要安装 pyaudio: pip install pyaudio")
            return False

        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
        except OSError as e:
            print(f"[AudioRecorder] 无法打开麦克风: {e}")
            p.terminate()
            return False

        print(f"[AudioRecorder] 录音开始 ({duration} 秒)...")
        frames: list[bytes] = []
        n_chunks = int(self.sample_rate / self.chunk * duration)

        for i in range(n_chunks):
            data = stream.read(self.chunk, exception_on_overflow=False)
            frames.append(data)
            if (i + 1) % 20 == 0:
                elapsed = (i + 1) * self.chunk / self.sample_rate
                print(f"  录音中... {elapsed:.1f}s / {duration}s")

        print("[AudioRecorder] 录音完成")

        stream.stop_stream()
        stream.close()

        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))

        p.terminate()
        print(f"[AudioRecorder] 已保存: {output_path}")
        return True


def record_wav(duration: float, output_path: Union[str, Path]) -> bool:
    """便捷函数：录 duration 秒到 output_path。"""
    return AudioRecorder().record(duration, output_path)
