"""
大模型润色 —— 把 LSTM 识别出的离散手语词组合成自然语句。

最小用法：
    from cloud import polish
    sentence = polish(["我", "头", "痛"])   # → "我头痛"

需要更多控制 / 流式输出时使用 LLMPolisher 类。
"""

from __future__ import annotations

from typing import Iterator, Optional

from openai import OpenAI

from .config import ARK_BASE_URL, ARK_LLM_MODEL, require_ark_key


DEFAULT_SYSTEM_PROMPT = (
    "你是一个手语翻译助手。用户通过手语识别系统得到一组离散的中文词语，"
    "你需要把它们润色成一个通顺、自然的中文句子。\n"
    "规则：\n"
    "1. 只输出润色后的句子，不要解释、不要加引号、不要加额外文字。\n"
    "2. 保持原意不添加新信息，仅调整语序、补充必要连接词。\n"
    "3. 如果词语本身已能组成通顺短语，原样输出。\n"
    "4. 处理常见康复 / 医疗场景用语。"
)


class PolishError(RuntimeError):
    """润色调用失败。"""


class LLMPolisher:
    """大模型润色客户端，复用 OpenAI client 连接。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = ARK_BASE_URL,
        model: str = ARK_LLM_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self._client = OpenAI(
            api_key=api_key or require_ark_key(),
            base_url=base_url.rstrip("/"),
        )

    def polish(
        self,
        words: list[str],
        temperature: float = 0.3,
        max_tokens: int = 256,
    ) -> str:
        """同步润色，返回字符串。失败抛 PolishError。"""
        if not words:
            raise PolishError("输入词列表为空")

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": "手语识别结果: " + " ".join(words)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            raise PolishError(f"大模型调用失败: {e}") from e

    def polish_stream(
        self,
        words: list[str],
        temperature: float = 0.3,
        max_tokens: int = 256,
    ) -> Iterator[str]:
        """流式润色，逐 token yield。失败抛 PolishError。"""
        if not words:
            raise PolishError("输入词列表为空")

        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": "手语识别结果: " + " ".join(words)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield token
        except Exception as e:
            raise PolishError(f"大模型流式调用失败: {e}") from e


# 模块级单例 + 便捷函数
_default_polisher: Optional[LLMPolisher] = None


def polish(words: list[str]) -> str:
    """一键润色：手语词列表 → 自然语句。失败抛 PolishError。"""
    global _default_polisher
    if _default_polisher is None:
        _default_polisher = LLMPolisher()
    return _default_polisher.polish(words)
