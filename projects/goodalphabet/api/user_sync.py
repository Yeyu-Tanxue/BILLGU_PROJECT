import datetime
import hashlib
from fastapi import HTTPException

from database import get_db, _is_pg


SYNC_ERROR_CODE = "USER_SYNC_FAILED"
TRIAL_TOKENS = 50000


def _build_username(auth0_sub: str) -> str:
    digest = hashlib.sha1(auth0_sub.encode()).hexdigest()[:10]
    return f"auth0_{digest}"


def _upsert_profile(db, internal_user_id: int, claims: dict):
    auth0_sub = claims["sub"]
    email = claims.get("email")
    name = claims.get("name")
    avatar_url = claims.get("picture")

    if _is_pg():
        db.execute(
            "INSERT INTO user_profiles (internal_user_id, auth0_sub, email, name, avatar_url, last_login_at) "
            "VALUES (?,?,?,?,?,NOW()) "
            "ON CONFLICT (auth0_sub) DO UPDATE SET internal_user_id=EXCLUDED.internal_user_id, "
            "email=EXCLUDED.email, name=EXCLUDED.name, avatar_url=EXCLUDED.avatar_url, last_login_at=NOW()",
            (internal_user_id, auth0_sub, email, name, avatar_url),
        )
    else:
        now = datetime.datetime.utcnow().isoformat()
        db.execute(
            "INSERT INTO user_profiles (internal_user_id, auth0_sub, email, name, avatar_url, last_login_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(auth0_sub) DO UPDATE SET internal_user_id=excluded.internal_user_id, "
            "email=excluded.email, name=excluded.name, avatar_url=excluded.avatar_url, last_login_at=excluded.last_login_at",
            (internal_user_id, auth0_sub, email, name, avatar_url, now),
        )


def _ensure_trial_token_user(db, claims: dict):
    auth0_sub = claims["sub"]
    email = claims.get("email")
    name = claims.get("name")

    if _is_pg():
        db.execute(
            'INSERT INTO public."user" (user_id, tokens, name, email, hourly_requests, generated) '
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (user_id) DO UPDATE SET email=COALESCE(EXCLUDED.email, public.\"user\".email), "
            "name=COALESCE(EXCLUDED.name, public.\"user\".name)",
            (auth0_sub, TRIAL_TOKENS, name, email, 0, False),
        )
    else:
        db.execute(
            'INSERT OR IGNORE INTO "user" (user_id, tokens, name, email, hourly_requests, generated) '
            "VALUES (?,?,?,?,?,?)",
            (auth0_sub, TRIAL_TOKENS, name, email, 0, False),
        )
        db.execute(
            'UPDATE "user" SET email=COALESCE(?, email), name=COALESCE(?, name) WHERE user_id=?',
            (email, name, auth0_sub),
        )


def sync_auth0_user(claims: dict) -> dict:
    """幂等同步 Auth0 claims 到用户映射表，返回内部用户信息。"""
    auth0_sub = claims.get("sub")
    if not auth0_sub:
        raise HTTPException(401, "Auth0 claims 缺少 sub")

    db = get_db()
    try:
        profile = db.execute(
            "SELECT internal_user_id FROM user_profiles WHERE auth0_sub=?", (auth0_sub,)
        ).fetchone()

        internal_user_id = profile["internal_user_id"] if profile else None
        if not internal_user_id:
            username = _build_username(auth0_sub)
            existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not existing:
                # Auth0 用户不使用本地密码登录，password_hash 占位
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?,?)",
                    (username, "AUTH0_MANAGED"),
                )
                db.commit()
                existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            internal_user_id = existing["id"]

        _upsert_profile(db, internal_user_id, claims)
        _ensure_trial_token_user(db, claims)
        db.commit()

        return {
            "user_id": internal_user_id,
            "username": _build_username(auth0_sub),
            "auth0_sub": auth0_sub,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[user_sync] failed for sub={auth0_sub}: {e}")
        raise HTTPException(
            status_code=503,
            detail={"code": SYNC_ERROR_CODE, "message": "用户同步失败，请稍后重试"},
        )
    finally:
        db.close()
