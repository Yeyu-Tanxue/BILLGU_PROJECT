"""
云端 API 模块。

子模块：
    cloud.polish     大模型润色（手语词 → 自然语句）
    cloud.asr        语音识别（音频 → 文字）
    cloud.emergency  紧急求助推送（Server酱 → 微信）
    cloud.config     密钥与端点配置（从 .env 读）

便捷入口：
    from cloud import polish, transcribe, notify
"""

from .asr import ASRError, ASRRecognizer, transcribe
from .emergency import EmergencyError, notify
from .polish import LLMPolisher, PolishError, polish

__all__ = [
    "polish",
    "LLMPolisher",
    "PolishError",
    "transcribe",
    "ASRRecognizer",
    "ASRError",
    "notify",
    "EmergencyError",
]
