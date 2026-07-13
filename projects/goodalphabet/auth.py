import os
import json
import time
import hashlib
import urllib.request
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from dotenv import load_dotenv

from api.user_sync import sync_auth0_user

# 兼容本地开发：允许从项目根目录 .env 加载配置
load_dotenv()

AUTH0_ALGORITHMS = ['RS256']

# 复用 JWK 客户端（内置 JWKS 缓存），避免每次重新拉取
_jwk_client: PyJWKClient | None = None

# userinfo 缓存：token_hash -> (payload, expire_ts)
_userinfo_cache: dict[str, tuple[dict, float]] = {}
_USERINFO_TTL = 300  # 5 分钟


def _require_auth0_settings() -> tuple[str, str]:
    auth0_issuer = os.environ.get('AUTH0_ISSUER', '').strip()

    if not auth0_issuer:
        raise HTTPException(500, 'Auth0 配置缺失：请设置 AUTH0_ISSUER')
    issuer = auth0_issuer if auth0_issuer.endswith('/') else f'{auth0_issuer}/'
    auth0_audience = os.environ.get('AUTH0_AUDIENCE', '').strip()
    return issuer, auth0_audience


def _get_jwk_client(issuer: str) -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
        _jwk_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwk_client


def _fetch_userinfo(token: str, issuer: str) -> dict[str, Any]:
    """调用 Auth0 /userinfo，结果缓存 5 分钟。"""
    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _userinfo_cache.get(key)
    if cached and time.time() < cached[1]:
        return cached[0]

    userinfo_url = f"{issuer.rstrip('/')}/userinfo"
    req = urllib.request.Request(
        userinfo_url,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'User-Agent': 'goodalphabet-auth/1.0',
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f'[auth] userinfo request failed: {e}')
        raise HTTPException(401, '无效的 Auth0 Token')

    if not isinstance(payload, dict) or not payload.get('sub'):
        raise HTTPException(401, '无效的 Auth0 Token')

    _userinfo_cache[key] = (payload, time.time() + _USERINFO_TTL)
    return payload


def _decode_auth0_token(token: str) -> dict[str, Any]:
    issuer, audience = _require_auth0_settings()

    # 没有配置 audience（未在 Auth0 注册 API）→ 直接走 /userinfo（支持不透明 token）
    if not audience:
        return _fetch_userinfo(token, issuer)

    try:
        client = _get_jwk_client(issuer)
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=AUTH0_ALGORITHMS,
            audience=audience,
            issuer=issuer,
        )
    except jwt.ExpiredSignatureError:
        print('[auth] token expired')
        raise HTTPException(401, '登录已过期')
    except jwt.InvalidTokenError as e:
        # Auth0 可能签发不透明 token，回退到 /userinfo 验证（带缓存）
        print(f'[auth] not a local JWT, using userinfo fallback: {e}')
        return _fetch_userinfo(token, issuer)
    except HTTPException:
        raise
    except Exception as e:
        print(f'[auth] token verify failed: {e}')
        raise HTTPException(401, 'Auth0 Token 校验失败')


def get_current_user(request: Request) -> dict[str, Any]:
    """从 Auth0 Bearer Token 解析用户信息，失败抛 401"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        raise HTTPException(401, '未登录')

    payload = _decode_auth0_token(auth[7:])
    try:
        user = sync_auth0_user(payload)
        user['email'] = payload.get('email')
        user['name'] = payload.get('name')
        user['auth0_user_id'] = payload.get('sub')
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '用户同步失败，请稍后重试')
