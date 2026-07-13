import hashlib
import json
import math
import urllib.request
from urllib.error import HTTPError
from fastapi import HTTPException

from database import DATABASE_URL, get_db

DEFAULT_LIGHT_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_LIGHT_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_LIGHT_KEY = "4d46054a-23df-4324-b60f-c815fb689461"
DEFAULT_LIGHT_MODEL = "doubao-1-5-lite-32k-250115"

AI_BASE_URL = "https://api.iamhc.cn"
AI_MODEL = "auto"
TRIAL_TOKENS = 50000


def _is_pg():
    return DATABASE_URL.startswith("postgres")


def _user_table() -> str:
    return 'public."user"' if _is_pg() else '"user"'


def _estimate_tokens(*parts: str) -> int:
    text = "".join(part or "" for part in parts)
    return max(1, math.ceil(len(text) / 4))


def _ensure_token_user(auth0_user_id: str):
    db = get_db()
    try:
        row = db.execute(f"SELECT user_id, tokens FROM {_user_table()} WHERE user_id=?", (auth0_user_id,)).fetchone()
        if row:
            return row
        db.execute(
            f"INSERT INTO {_user_table()} (user_id, tokens, hourly_requests, generated) VALUES (?, ?, ?, ?)",
            (auth0_user_id, TRIAL_TOKENS, 0, False),
        )
        db.commit()
        return db.execute(f"SELECT user_id, tokens FROM {_user_table()} WHERE user_id=?", (auth0_user_id,)).fetchone()
    finally:
        db.close()


def _require_token_balance(auth0_user_id: str):
    row = _ensure_token_user(auth0_user_id)
    tokens = int(row.get("tokens") or 0)
    if tokens <= 0:
        raise HTTPException(402, "Token 不足，请购买会员后继续使用。")


def _deduct_user_tokens(auth0_user_id: str, amount: int):
    amount = max(1, int(amount or 1))
    db = get_db()
    try:
        if _is_pg():
            updated = db.execute(
                f"UPDATE {_user_table()} SET tokens=GREATEST(COALESCE(tokens, 0) - ?, 0) "
                "WHERE user_id=? AND COALESCE(tokens, 0) >= ? RETURNING tokens",
                (amount, auth0_user_id, amount),
            ).fetchone()
            if not updated:
                db.execute(f"UPDATE {_user_table()} SET tokens=0 WHERE user_id=?", (auth0_user_id,))
                db.commit()
                raise HTTPException(402, "Token 不足，请购买会员后继续使用。")
            db.commit()
            return

        row = db.execute(f"SELECT tokens FROM {_user_table()} WHERE user_id=?", (auth0_user_id,)).fetchone()
        current = int(row["tokens"] or 0) if row else 0
        if current < amount:
            if row:
                db.execute(f"UPDATE {_user_table()} SET tokens=0 WHERE user_id=?", (auth0_user_id,))
                db.commit()
            raise HTTPException(402, "Token 不足，请购买会员后继续使用。")
        db.execute(f"UPDATE {_user_table()} SET tokens=? WHERE user_id=?", (current - amount, auth0_user_id))
        db.commit()
    finally:
        db.close()

def _make_ai_request(prompt, auth0_user_id: str, max_tokens: int, stream: bool):
    if not auth0_user_id or not str(auth0_user_id).strip():
        raise HTTPException(401, "缺少 Auth0 用户标识")
    api_url = DEFAULT_LIGHT_API_URL
    body = json.dumps({
        "model": DEFAULT_LIGHT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": stream,
        **({"stream_options": {"include_usage": True}} if stream else {}),
    }).encode()
    return urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {DEFAULT_LIGHT_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )


def _extract_ai_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            try:
                payload = json.loads(body)
                # 检查是否是 token 不足的错误
                error_msg = payload.get("error_description") or payload.get("error") or payload.get("message") or ""
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", "")
                error_msg = str(error_msg).lower()
                if (
                    exc.code == 429
                    or "concurrency" in error_msg
                    or "rate_limited" in error_msg
                    or "too many requests" in error_msg
                ):
                    return "AI 服务繁忙：并发数已达上限，请稍后再试"
                if "quota" in error_msg:
                    return "Token 不足，无法完成请求。请稍后重试或检查配额。"
                
                for key in ("error_description", "error", "message", "detail"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            except (json.JSONDecodeError, AttributeError):
                pass
            return body
        return getattr(exc, "reason", None) or f"HTTP Error {exc.code}"
    message = str(exc).strip()
    return message or "AI 调用失败"


def call_ai(prompt, auth0_user_id: str, max_tokens=2000):
    """统一 AI 调用（非流式）"""
    _require_token_balance(auth0_user_id)
    req = _make_ai_request(prompt, auth0_user_id, max_tokens, stream=False)
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
        if "choices" not in resp or not resp["choices"]:
            error_msg = resp.get("error", {}).get("message") if isinstance(resp.get("error"), dict) else resp.get("error", "未知错误")
            raise RuntimeError(str(error_msg))
        content = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage") or {}
        spent = usage.get("total_tokens") or _estimate_tokens(prompt, content)
        _deduct_user_tokens(auth0_user_id, spent)
        return content
    except HTTPException:
        raise
    except Exception as exc:
        error_msg = _extract_ai_error_message(exc)
        raise RuntimeError(error_msg) from exc


def call_ai_stream(prompt, auth0_user_id: str, max_tokens=2000):
    """流式 AI 调用，逐块 yield 文本片段"""
    _require_token_balance(auth0_user_id)
    req = _make_ai_request(prompt, auth0_user_id, max_tokens, stream=True)
    output_chunks: list[str] = []
    usage_total_tokens: int | None = None
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                    # 检查是否是错误响应
                    if "error" in payload:
                        error_msg = payload["error"]
                        if isinstance(error_msg, dict):
                            error_msg = error_msg.get("message", str(error_msg))
                        raise RuntimeError(str(error_msg))
                    usage = payload.get("usage")
                    if isinstance(usage, dict) and usage.get("total_tokens"):
                        usage_total_tokens = int(usage["total_tokens"])
                    delta = payload.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        output_chunks.append(delta)
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        spent = usage_total_tokens or _estimate_tokens(prompt, "".join(output_chunks))
        _deduct_user_tokens(auth0_user_id, spent)
    except HTTPException:
        raise
    except Exception as exc:
        error_msg = _extract_ai_error_message(exc)
        raise RuntimeError(error_msg) from exc
