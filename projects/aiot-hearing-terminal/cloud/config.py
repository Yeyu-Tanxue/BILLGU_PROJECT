"""
云端 API 配置 —— 从 .env 读密钥，集中管理。

.env 字段：
    ARK_API_KEY      大模型网关 Key (手语润色用，sk-xxx)
    ARK_BASE_URL     网关 base URL (可选)
    ARK_LLM_MODEL    润色模型 (默认 Doubao-Seed-1.6)
    ASR_API_KEY      豆包大模型录音识别 x-api-key (语音转文字用，UUID 形式)
    ASR_RESOURCE_ID  ASR 资源 ID (默认 volc.seedasr.auc)
"""

from __future__ import annotations

import os
from pathlib import Path

# 自动加载项目根目录的 .env（无 python-dotenv 时静默跳过）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


# ---- 大模型网关（手语润色）----
ARK_API_KEY: str = os.getenv("ARK_API_KEY", "")
ARK_BASE_URL: str = os.getenv("ARK_BASE_URL", "https://ai-gateway.vei.volces.com/v1")
ARK_LLM_MODEL: str = os.getenv("ARK_LLM_MODEL", "Doubao-Seed-1.6")

# ---- 豆包大模型录音文件识别（语音转文字，header 鉴权）----
# auc 异步：submit 提交 → query 轮询。x-api-key 形如 UUID，与 ARK_API_KEY 不同。
ASR_API_KEY: str = os.getenv("ASR_API_KEY", "")
ASR_RESOURCE_ID: str = os.getenv("ASR_RESOURCE_ID", "volc.seedasr.auc")

# ---- 紧急求助推送：Server酱 SendKey（sct.ftqq.com，微信扫码获取）----
SERVER_CHAN_KEY: str = os.getenv("SERVER_CHAN_KEY", "")


def require_ark_key() -> str:
    """获取大模型网关密钥，未配置时抛错。"""
    if not ARK_API_KEY:
        raise RuntimeError(
            "ARK_API_KEY 未配置。请在项目根目录的 .env 文件中设置 ARK_API_KEY=sk-xxx"
        )
    return ARK_API_KEY


def has_native_asr() -> bool:
    """是否配置了豆包大模型 ASR 凭证。"""
    return bool(ASR_API_KEY)
