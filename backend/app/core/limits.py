from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.models import Resume, Role, UsageCounter, User

LimitKind = Literal["interview", "message"]
_ANY_KIND = Literal["interview", "message", "resume"]
_SETTING_NAME = {"interview": "INTERVIEWS", "message": "MESSAGES", "resume": "RESUMES"}
_COUNTER_COLUMN = {"interview": "interviews_started", "message": "messages_sent"}
_LABEL = {"interview": "interviews", "message": "messages", "resume": "resume uploads"}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def seconds_until_utc_midnight(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return max(1, int((tomorrow - now).total_seconds()))


def get_limit(role: str, kind: _ANY_KIND) -> int | None:
    """Daily limit for a role from settings. None = unlimited (admin)."""
    if role == Role.admin.value:
        return None
    prefix = "GUEST" if role == Role.guest.value else "USER"
    return int(getattr(get_settings(), f"LIMIT_{prefix}_{_SETTING_NAME[kind]}_PER_DAY"))


def _limit_error(role: str, kind: _ANY_KIND, limit: int) -> AppError:
    wait = seconds_until_utc_midnight()
    hours, minutes = divmod(wait // 60, 60)
    msg = f"You've reached today's limit of {limit} {_LABEL[kind]}."
    if role == Role.guest.value:
        msg += " Create a free account to get a higher daily limit."
    msg += f" It resets in {hours}h {minutes}m (midnight UTC)."
    return AppError("rate_limited", msg, 429, {"Retry-After": str(wait)})


async def check_and_increment(db: AsyncSession, user: User, kind: LimitKind) -> int:
    """Atomically count one `interview`/`message` for today or raise AppError 429.

    Single upsert with `WHERE counter < limit`, so concurrent requests cannot exceed the limit.
    Commits on success (the counter is independent of the caller's other work).
    Returns the new count for today.
    """
    role, user_id = user.role, user.id  # read now: ORM attributes expire after a rollback/commit
    limit = get_limit(role, kind)
    if limit is not None and limit <= 0:
        raise _limit_error(role, kind, limit)

    column_name = _COUNTER_COLUMN[kind]
    column = getattr(UsageCounter, column_name)
    stmt = (
        pg_insert(UsageCounter)
        .values(user_id=user_id, day=utc_today(), **{column_name: 1})
        .on_conflict_do_update(
            index_elements=[UsageCounter.user_id, UsageCounter.day],
            set_={column_name: column + 1},
            where=(column < limit) if limit is not None else None,
        )
        .returning(column)
    )
    new_count = (await db.execute(stmt)).scalar_one_or_none()
    if new_count is None:  # conflict row exists and WHERE failed -> limit reached
        raise _limit_error(role, kind, limit or 0)
    await db.commit()
    return new_count


async def check_resume_limit(db: AsyncSession, user: User) -> None:
    """Raise AppError 429 if the user already uploaded today's maximum number of resumes."""
    limit = get_limit(user.role, "resume")
    if limit is None:
        return
    start = datetime.combine(utc_today(), time.min, tzinfo=timezone.utc)
    count = await db.scalar(
        select(func.count()).select_from(Resume).where(Resume.user_id == user.id, Resume.created_at >= start)
    )
    if (count or 0) >= limit:
        raise _limit_error(user.role, "resume", limit)
