from datetime import datetime, timezone

import jwt
import pytest

from app.config import get_settings
from app.core.errors import AppError
from app.core.security import ALGORITHM, create_access_token, decode_token, hash_password, verify_password


async def test_password_roundtrip() -> None:
    h = await hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert await verify_password("s3cret-pass", h) and not await verify_password("nope", h)
    assert await verify_password("x", None) is False


def test_guest_token_outlives_user_token() -> None:
    s = get_settings()
    g = decode_token(create_access_token("u1", "guest"))
    u = decode_token(create_access_token("u1", "user"))
    assert g["sub"] == "u1" and g["role"] == "guest" and u["role"] == "user"
    assert g["exp"] - u["exp"] == pytest.approx(s.GUEST_TOKEN_EXPIRE_DAYS * 86400 - s.ACCESS_TOKEN_EXPIRE_MINUTES * 60, abs=5)


def test_expired_and_tampered_tokens() -> None:
    key = get_settings().SECRET_KEY
    expired = jwt.encode({"sub": "u", "role": "user", "exp": datetime(2020, 1, 1, tzinfo=timezone.utc)}, key, algorithm=ALGORITHM)
    with pytest.raises(AppError) as e:
        decode_token(expired)
    assert e.value.code == "token_expired"
    with pytest.raises(AppError) as e2:
        decode_token(create_access_token("u", "user") + "x")
    assert e2.value.code == "invalid_token"
