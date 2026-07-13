"""
语音识别 —— 音频字节流 / 文件 → 文字。

走火山「豆包大模型录音文件识别」(auc bigmodel)，异步两段式：
  ① submit  POST /api/v3/auc/bigmodel/submit   提交音频(base64)
  ② query   POST /api/v3/auc/bigmodel/query    轮询取结果
鉴权走 header：x-api-key + X-Api-Resource-Id(volc.seedasr.auc)。
凭证在 .env 的 ASR_API_KEY（UUID 形式，与润色用的 ARK_API_KEY 不同）。

最小用法：
    from cloud import transcribe
    text = transcribe(wav_bytes)        # bytes
    text = transcribe("audio.wav")      # 文件路径
"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Optional, Union

import requests

from .config import ASR_API_KEY, ASR_RESOURCE_ID, has_native_asr

SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

# X-Api-Status-Code 含义
ST_SUCCESS = "20000000"   # 成功 / 任务完成
ST_QUEUED = "20000001"    # 排队中
ST_RUNNING = "20000002"   # 处理中
ST_SILENT = "20000003"    # 静音音频


class ASRError(RuntimeError):
    """语音识别调用失败。"""


class ASRRecognizer:
    """豆包大模型录音文件识别客户端。"""

    def __init__(
        self,
        api_key: str = ASR_API_KEY,
        resource_id: str = ASR_RESOURCE_ID,
    ):
        self.api_key = api_key
        self.resource_id = resource_id

    def transcribe(
        self,
        audio: Union[bytes, str, Path],
        *,
        sample_rate: int = 16000,
        fmt: str = "wav",
        poll_interval: float = 0.5,
        timeout: float = 30.0,
    ) -> str:
        """识别音频，返回纯文本。失败抛 ASRError。"""
        if not self.api_key:
            raise ASRError("ASR_API_KEY 未配置（.env 里填豆包大模型录音识别的 x-api-key）")

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.exists():
                raise ASRError(f"音频文件不存在: {path}")
            audio_bytes = path.read_bytes()
            fmt = path.suffix.lstrip(".").lower() or fmt
        elif isinstance(audio, bytes):
            audio_bytes = audio
        else:
            raise ASRError(f"audio 参数类型不支持: {type(audio).__name__}")

        request_id = str(uuid.uuid4())
        logid = self._submit(audio_bytes, request_id, sample_rate=sample_rate, fmt=fmt)
        return self._poll(request_id, logid, poll_interval=poll_interval, timeout=timeout)

    def _headers(self, request_id: str, logid: Optional[str] = None) -> dict:
        h = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        if logid:
            h["X-Tt-Logid"] = logid
        return h

    def _submit(self, audio_bytes: bytes, request_id: str, *, sample_rate: int, fmt: str) -> str:
        payload = {
            "user": {"uid": "esp32_user"},
            "audio": {
                "data": base64.b64encode(audio_bytes).decode("utf-8"),
                "format": fmt,
                "codec": "raw",
                "rate": sample_rate,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
            },
        }
        try:
            resp = requests.post(SUBMIT_URL, headers=self._headers(request_id),
                                 json=payload, timeout=30)
        except requests.RequestException as e:
            raise ASRError(f"submit 请求失败: {e}") from e

        code = resp.headers.get("X-Api-Status-Code", "")
        if code != ST_SUCCESS:
            msg = resp.headers.get("X-Api-Message", resp.text[:300])
            raise ASRError(f"submit 失败 [{code}]: {msg}")
        return resp.headers.get("X-Tt-Logid", "")

    def _poll(self, request_id: str, logid: str, *, poll_interval: float, timeout: float) -> str:
        deadline = time.time() + timeout
        while True:
            try:
                resp = requests.post(QUERY_URL, headers=self._headers(request_id, logid),
                                     json={}, timeout=30)
            except requests.RequestException as e:
                raise ASRError(f"query 请求失败: {e}") from e

            code = resp.headers.get("X-Api-Status-Code", "")
            if code == ST_SUCCESS:
                return self._extract_text(resp)
            if code == ST_SILENT:
                return ""   # 静音 → 空文本
            if code not in (ST_QUEUED, ST_RUNNING):
                msg = resp.headers.get("X-Api-Message", resp.text[:300])
                raise ASRError(f"query 失败 [{code}]: {msg}")
            if time.time() > deadline:
                raise ASRError(f"query 轮询超时（{timeout}s 仍未完成，最后状态 {code}）")
            time.sleep(poll_interval)

    @staticmethod
    def _extract_text(resp: requests.Response) -> str:
        try:
            data = resp.json()
        except ValueError as e:
            raise ASRError(f"query 返回非 JSON: {resp.text[:200]}") from e
        result = data.get("result", {})
        if isinstance(result, dict) and result.get("text") is not None:
            return result["text"].strip()
        # 兜底：从 utterances 拼
        utts = result.get("utterances") if isinstance(result, dict) else None
        if utts:
            return "".join(u.get("text", "") for u in utts).strip()
        raise ASRError(f"query 结果无 text 字段: {str(data)[:300]}")


# 模块级单例 + 便捷函数
_default_recognizer: Optional[ASRRecognizer] = None


def transcribe(
    audio: Union[bytes, str, Path],
    *,
    sample_rate: int = 16000,
    fmt: str = "wav",
) -> str:
    """一键识别：bytes / 文件路径 → 文本。失败抛 ASRError。"""
    global _default_recognizer
    if _default_recognizer is None:
        _default_recognizer = ASRRecognizer()
    return _default_recognizer.transcribe(audio, sample_rate=sample_rate, fmt=fmt)
