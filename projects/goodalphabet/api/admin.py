from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth import get_current_user
from database import DATABASE_URL, get_db

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

router = APIRouter()


def _user_table() -> str:
    return 'public."user"' if DATABASE_URL.startswith("postgres") else '"user"'


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _admin_emails() -> set[str]:
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _require_admin(request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    email = (user.get("email") or "").strip().lower()
    allowed = _admin_emails()
    if not allowed:
        raise HTTPException(status_code=403, detail="ADMIN_EMAILS 未配置")
    if email not in allowed:
        raise HTTPException(status_code=403, detail="没有后台权限")
    return user


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _serialize_user(row: dict[str, Any]) -> dict[str, Any]:
    last_payment_at = _parse_dt(row.get("last_payment_time"))
    expires_at = last_payment_at + timedelta(days=30) if last_payment_at else None
    active = bool(expires_at and expires_at > _now_utc())
    return {
        "user_id": row.get("user_id"),
        "name": row.get("name"),
        "email": row.get("email"),
        "tokens": int(row.get("tokens") or 0),
        "hourly_requests": int(row.get("hourly_requests") or 0),
        "generated": row.get("generated"),
        "stripe_subscription": row.get("stripe_subscription"),
        "stripe_customer": row.get("stripe_customer"),
        "last_payment_time": last_payment_at.isoformat() if last_payment_at else None,
        "access_expires_at": expires_at.isoformat() if expires_at else None,
        "active": active,
        "time": _parse_dt(row.get("time")).isoformat() if _parse_dt(row.get("time")) else None,
        "last_request_time": _parse_dt(row.get("last_request_time")).isoformat()
        if _parse_dt(row.get("last_request_time"))
        else None,
    }


@router.get("/admin/dashboard")
async def admin_dashboard(request: Request, q: str = "", limit: int = 50):
    admin = _require_admin(request)
    safe_limit = min(max(limit, 1), 200)
    table = _user_table()
    db = get_db()
    try:
        total = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
        paid = db.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE last_payment_time IS NOT NULL"
        ).fetchone()["count"]
        token_sum = db.execute(
            f"SELECT COALESCE(SUM(tokens), 0) AS tokens FROM {table}"
        ).fetchone()["tokens"]
        active_cutoff = (_now_utc() - timedelta(days=30)).isoformat()
        active_paid = db.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE last_payment_time > ?",
            (active_cutoff,),
        ).fetchone()["count"]

        params: tuple[Any, ...]
        where = ""
        if q.strip():
            needle = f"%{q.strip()}%"
            where = "WHERE user_id ILIKE ? OR email ILIKE ? OR name ILIKE ?" if DATABASE_URL.startswith("postgres") else "WHERE user_id LIKE ? OR email LIKE ? OR name LIKE ?"
            params = (needle, needle, needle, safe_limit)
        else:
            params = (safe_limit,)

        rows = db.execute(
            f"""
            SELECT user_id, tokens, name, email, time, hourly_requests, last_request_time,
                   generated, stripe_subscription, stripe_customer, last_payment_time
            FROM {table}
            {where}
            ORDER BY time DESC NULLS LAST
            LIMIT ?
            """,
            params,
        ).fetchall()

        return {
            "admin_email": admin.get("email"),
            "database": {
                "kind": "postgres" if DATABASE_URL.startswith("postgres") else "sqlite",
                "configured": bool(DATABASE_URL),
            },
            "summary": {
                "total_users": int(total or 0),
                "paid_users": int(paid or 0),
                "active_paid_users": int(active_paid or 0),
                "total_tokens": int(token_sum or 0),
            },
            "users": [_serialize_user(row) for row in rows],
        }
    finally:
        db.close()


class AdminUserUpdate(BaseModel):
    tokens: int | None = None
    grant_days: int | None = None
    clear_payment: bool = False


@router.patch("/admin/users/{user_id:path}")
async def update_admin_user(user_id: str, payload: AdminUserUpdate, request: Request):
    _require_admin(request)
    updates: list[str] = []
    params: list[Any] = []

    if payload.tokens is not None:
        updates.append("tokens=?")
        params.append(max(0, payload.tokens))
    if payload.grant_days is not None:
        days = min(max(payload.grant_days, 1), 365)
        updates.append("last_payment_time=?")
        params.append((_now_utc() - timedelta(days=30 - days)).isoformat())
        updates.append("stripe_subscription=COALESCE(stripe_subscription, ?)")
        params.append(f"manual_grant_{_now_utc().strftime('%Y%m%d%H%M%S')}")
    if payload.clear_payment:
        updates.extend(["last_payment_time=NULL", "stripe_subscription=NULL", "stripe_customer=NULL"])

    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新字段")

    params.append(user_id)
    db = get_db()
    try:
        db.execute(f"UPDATE {_user_table()} SET {', '.join(updates)} WHERE user_id=?", tuple(params))
        db.commit()
        row = db.execute(
            f"""
            SELECT user_id, tokens, name, email, time, hourly_requests, last_request_time,
                   generated, stripe_subscription, stripe_customer, last_payment_time
            FROM {_user_table()}
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        return _serialize_user(row)
    finally:
        db.close()
