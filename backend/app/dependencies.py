import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_token, password_version
from app.database import get_db
from app.models import Role, User

_bearer = HTTPBearer(auto_error=False)
LAST_SEEN_THROTTLE = timedelta(minutes=1)  # avoid a DB write on every request

DbSession = Annotated[AsyncSession, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def _load_user(token: str, db: AsyncSession, leeway_seconds: int = 0) -> User:
    claims = decode_token(token, leeway_seconds)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError:
        raise AppError("invalid_token", "Invalid authentication token.", 401, {"WWW-Authenticate": "Bearer"}) from None
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("invalid_token", "Account no longer exists.", 401, {"WWW-Authenticate": "Bearer"})
    pv = claims.get("pv")
    if pv and pv != password_version(user.password_hash):  # password changed after this token was issued
        raise AppError("invalid_token", "Your password was changed. Please sign in again.", 401, {"WWW-Authenticate": "Bearer"})
    return user


async def get_current_user(creds: Credentials, db: DbSession) -> User:
    if creds is None:
        raise AppError("not_authenticated", "Authentication required.", 401, {"WWW-Authenticate": "Bearer"})
    user = await _load_user(creds.credentials, db)
    now = datetime.now(timezone.utc)
    if user.last_seen_at is None or now - user.last_seen_at > LAST_SEEN_THROTTLE:
        user.last_seen_at = now
        await db.commit()
    return user


async def user_from_token(token: str, db: AsyncSession, leeway_seconds: int = 0) -> User:
    """Public wrapper for /auth/refresh: like get_current_user but tolerates a recently expired token."""
    return await _load_user(token, db, leeway_seconds)


async def get_optional_user(creds: Credentials, db: DbSession) -> User | None:
    """Valid token -> User, anything else (missing/expired/invalid) -> None. Never raises."""
    if creds is None:
        return None
    try:
        return await _load_user(creds.credentials, db)
    except AppError:
        return None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_role(*roles: str | Role):
    """Dependency factory: `Depends(require_role("admin"))` -> 403 forbidden for other roles."""
    allowed = {r.value if isinstance(r, Role) else r for r in roles}

    async def _checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise AppError("forbidden", "You don't have permission to do that.", 403)
        return user

    return _checker
