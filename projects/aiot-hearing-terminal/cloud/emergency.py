"""
紧急求助推送 —— 把求助消息推到手机（Server酱 / SCT，微信接收）。

开通：手机微信扫码登录 https://sct.ftqq.com → 拿 SendKey（形如 SCTxxxxxx）
      填进 .env：SERVER_CHAN_KEY=SCTxxxxxx

最小用法：
    from cloud import notify
    notify("我需要帮助")                      # 默认标题
    notify("我在客厅摔倒了", title="紧急求助")  # 自定义标题
"""

from __future__ import annotations

from typing import Optional

import requests

from .config import SERVER_CHAN_KEY


class EmergencyError(RuntimeError):
    """推送失败。"""


def notify(
    message: str,
    title: str = "⚠️ 听障终端紧急求助",
    key: Optional[str] = None,
    timeout: float = 10.0,
) -> dict:
    """
    推送一条紧急求助消息到微信。成功返回响应 dict，失败抛 EmergencyError。

    参数:
        message: 正文（支持 markdown）
        title:   标题（微信消息标题）
        key:     Server酱 SendKey，默认读 .env 的 SERVER_CHAN_KEY
    """
    sendkey = key or SERVER_CHAN_KEY
    if not sendkey:
        raise EmergencyError(
            "SERVER_CHAN_KEY 未配置。微信扫码 https://sct.ftqq.com 拿 SendKey，"
            "填进 .env：SERVER_CHAN_KEY=SCTxxxxxx"
        )

    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    try:
        resp = requests.post(
            url,
            data={"title": title, "desp": message},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise EmergencyError(f"推送请求失败（网络问题？）: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise EmergencyError(f"推送返回非 JSON: {resp.text[:200]}") from e

    # Server酱 成功 code == 0
    if data.get("code") != 0:
        raise EmergencyError(f"推送失败: {data}")
    return data
