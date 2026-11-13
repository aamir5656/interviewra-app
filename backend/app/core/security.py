import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.core.errors import AppError
from app.models import Role

ALGORITHM = "HS256"
_BEARER = {"WWW-Authenticate": "Bearer"}

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_dummy_hash: str | None = None


async def hash_password(password: str) -> str:
    """bcrypt is CPU-bound: run it in a worker thread so the event loop stays free."""
    return await asyncio.to_thread(_pwd.hash, password)


async def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify in a thread. With no stored hash, burn equal time against a dummy hash (anti user-enumeration)."""
    global _dummy_hash
    if not password_hash:
        if _dummy_hash is None:
            _dummy_hash = await hash_password(uuid.uuid4().hex)
        await asyncio.to_thread(_pwd.verify, password, _dummy_hash)
        return False
    try:
        return await asyncio.to_thread(_pwd.verify, password, password_hash)
    except ValueError:
        return False


def password_version(password_hash: str | None) -> str | None:
    """Short fingerprint of the stored hash. Tokens carry it (claim `pv`), so changing the password invalidates them."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16] if password_hash else None


def create_access_token(user_id: uuid.UUID | str, role: str, password_hash: str | None = None) -> str:
    """JWT with claims sub, role, exp (+ pv for accounts with a password).
    Guests live GUEST_TOKEN_EXPIRE_DAYS, others ACCESS_TOKEN_EXPIRE_MINUTES."""
    s = get_settings()
    if role == Role.guest.value:
        ttl = timedelta(days=s.GUEST_TOKEN_EXPIRE_DAYS)
    else:
        ttl = timedelta(minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims: dict[str, Any] = {"sub": str(user_id), "role": role, "exp": datetime.now(timezone.utc) + ttl}
    if pv := password_version(password_hash):
        claims["pv"] = pv
    return jwt.encode(claims, s.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, leeway_seconds: int = 0) -> dict[str, Any]:
    """Return verified claims or raise AppError 401 (token_expired / invalid_token).
    `leeway_seconds` accepts a token that expired that recently (used only by /auth/refresh)."""
    try:
        return jwt.decode(
            token, get_settings().SECRET_KEY, algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "role"]}, leeway=leeway_seconds,
        )
    except jwt.ExpiredSignatureError:
        raise AppError("token_expired", "Your session has expired. Please sign in again.", 401, _BEARER) from None
    except jwt.InvalidTokenError:
        raise AppError("invalid_token", "Invalid authentication token.", 401, _BEARER) from None
