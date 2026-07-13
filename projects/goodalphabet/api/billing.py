from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from auth import get_current_user
from database import DATABASE_URL, get_db

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

router = APIRouter()

PRODUCT_ID = "alphebet_month_access"
ACCESS_DAYS = int(os.environ.get("STRIPE_MONTH_ACCESS_DAYS", "30") or "30")
STRIPE_API_VERSION = "2026-04-22.dahlia"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


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


def _user_table() -> str:
    return 'public."user"' if DATABASE_URL.startswith("postgres") else '"user"'


def _checkout_configured() -> bool:
    return bool(
        os.environ.get("STRIPE_SECRET_KEY", "").strip()
        and (
            os.environ.get("STRIPE_MONTH_ACCESS_PRICE_ID", "").strip()
            or os.environ.get("NEXT_PUBLIC_STRIPE_MONTH_ACCESS_PRICE_ID", "").strip()
        )
    )


def _get_price_id() -> str:
    price_id = (
        os.environ.get("STRIPE_MONTH_ACCESS_PRICE_ID", "").strip()
        or os.environ.get("NEXT_PUBLIC_STRIPE_MONTH_ACCESS_PRICE_ID", "").strip()
    )
    if not price_id:
        raise HTTPException(status_code=503, detail="月度访问价格未配置")
    return price_id


def _get_base_url(request: Request) -> str:
    app_base_url = os.environ.get("APP_BASE_URL", "").strip()
    if app_base_url:
        return app_base_url.rstrip("/")

    origin = request.headers.get("origin", "")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    referer = request.headers.get("referer", "")
    if referer:
        parsed = urlsplit(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    parsed = urlsplit(str(request.base_url))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


def _get_billing_user(db, auth0_id: str, email: str | None = None):
    table = _user_table()
    row = db.execute(
        f"SELECT user_id, email, tokens, stripe_subscription, stripe_customer, last_payment_time FROM {table} WHERE user_id=?",
        (auth0_id,),
    ).fetchone()
    if row or not email:
        return row
    return db.execute(
        f"SELECT user_id, email, tokens, stripe_subscription, stripe_customer, last_payment_time FROM {table} WHERE email=?",
        (email,),
    ).fetchone()


def _ensure_billing_user(db, auth0_id: str, email: str | None = None, name: str | None = None):
    table = _user_table()
    row = _get_billing_user(db, auth0_id, email)
    if row:
        return row

    db.execute(
        f"INSERT INTO {table} (user_id, tokens, name, email, hourly_requests, generated) VALUES (?, ?, ?, ?, ?, ?)",
        (auth0_id, 50000, name, email, 0, False),
    )
    db.commit()
    return _get_billing_user(db, auth0_id, email)


def _build_status(row, checkout_configured: bool) -> dict[str, Any]:
    now = _now_utc()
    last_payment_at = _parse_dt(row["last_payment_time"]) if row else None
    tokens = int(row["tokens"] or 0) if row else 0
    expires_at = last_payment_at + timedelta(days=ACCESS_DAYS) if last_payment_at else None
    active = bool(expires_at and expires_at > now)
    days_remaining = None
    if active and expires_at:
        days_remaining = max(1, (expires_at - now).days)

    return {
        "active": active,
        "has_access": active or tokens > 0,
        "tokens": tokens,
        "checkout_configured": checkout_configured,
        "access_expires_at": _iso(expires_at),
        "days_remaining": days_remaining,
        "last_payment_at": _iso(last_payment_at),
    }


@router.get("/billing/status")
async def billing_status(request: Request):
    user = get_current_user(request)
    db = get_db()
    try:
        row = _get_billing_user(db, user["auth0_user_id"], user.get("email"))
        return _build_status(row, _checkout_configured())
    finally:
        db.close()


@router.post("/billing/checkout")
async def create_checkout_session(request: Request):
    user = get_current_user(request)

    try:
        body = await request.json()
    except Exception:
        body = {}

    source = body.get("source") if isinstance(body, dict) else None
    source_path = source if isinstance(source, str) and source.startswith("/") else "/setup"
    encoded_source = quote(source_path, safe="/")

    secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        raise HTTPException(status_code=503, detail="Stripe 未配置")

    stripe.api_key = secret_key
    stripe.api_version = STRIPE_API_VERSION

    auth0_id = user["auth0_user_id"]
    db = get_db()
    try:
        _ensure_billing_user(db, auth0_id, user.get("email"), user.get("name"))
    finally:
        db.close()

    metadata: dict[str, str] = {
        "product": PRODUCT_ID,
        "auth0Id": auth0_id,
        "source": source_path,
    }
    if user.get("email"):
        metadata["auth0Email"] = user["email"]

    base_url = _get_base_url(request)
    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": _get_price_id(), "quantity": 1}],
        success_url=f"{base_url}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}&returnTo={encoded_source}",
        cancel_url=f"{base_url}/billing?checkout=cancelled&returnTo={encoded_source}",
        client_reference_id=auth0_id,
        metadata=metadata,
        customer_email=user.get("email") or None,
        allow_promotion_codes=True,
    )

    return {"url": checkout_session.url}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    # Debug: 打印所有 headers
    all_headers = dict(request.headers)
    print("=== STRIPE WEBHOOK DEBUG ===")
    print(f"All headers: {all_headers}")
    
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    signature = request.headers.get("stripe-signature")
    
    # Debug: 打印环境变量和签名状态
    print(f"STRIPE_WEBHOOK_SECRET exists: {bool(secret)}")
    print(f"STRIPE_WEBHOOK_SECRET prefix: {secret[:10] if secret else 'MISSING'}")
    print(f"stripe-signature exists: {bool(signature)}")
    print(f"stripe-signature value: {signature}")
    
    if not secret:
        raise HTTPException(status_code=400, detail=f"Webhook Secret 缺失 | headers: {list(all_headers.keys())}")
    
    if not signature:
        raise HTTPException(status_code=400, detail=f"stripe-signature header 缺失 | 收到的 headers: {list(all_headers.keys())}")
    
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook 验证失败: {exc}") from exc

    # ... 后续逻辑不变
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook 验证失败: {exc}") from exc

    if event["type"] != "checkout.session.completed":
        return PlainTextResponse("ignored", status_code=200)

    session = event["data"]["object"]
    session = session.to_dict()
    metadata = session.get("metadata") or {}
    if metadata.get("product") != PRODUCT_ID:
        return PlainTextResponse("ignored", status_code=200)
    if session.get("payment_status") != "paid":
        return PlainTextResponse("ignored", status_code=200)

    auth0_id = session.get("client_reference_id") or metadata.get("auth0Id")
    if not auth0_id:
        return PlainTextResponse("missing auth0 id", status_code=200)

    customer_id = session.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    checkout_session_id = session.get("id")
    if not isinstance(checkout_session_id, str):
        raise HTTPException(status_code=400, detail="缺少 checkout session")

    db = get_db()
    try:
        auth0_email = metadata.get("auth0Email") or session.get("customer_email")
        profile = _ensure_billing_user(
            db,
            str(auth0_id),
            auth0_email if isinstance(auth0_email, str) else None,
            None,
        )
        if not profile:
            return PlainTextResponse("user not found", status_code=200)
        if profile.get("stripe_subscription") == checkout_session_id:
            return PlainTextResponse("ok", status_code=200)

        db.execute(
            f"UPDATE {_user_table()} SET stripe_subscription=?, stripe_customer=?, last_payment_time=? WHERE user_id=?",
            (
                checkout_session_id,
                customer_id if isinstance(customer_id, str) else None,
                _iso(_now_utc()),
                profile["user_id"],
            ),
        )
        db.commit()
        return PlainTextResponse("ok", status_code=200)
    finally:
        db.close()
