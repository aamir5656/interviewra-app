"""Periodic housekeeping so the free database does not fill up with abandoned data."""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session_factory
from app.models import InterviewSession, SessionStatus, UsageCounter, User

logger = logging.getLogger("app")

FIRST_RUN_DELAY_SECONDS = 60
COUNTER_RETENTION_DAYS = 7


async def purge_stale(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Delete stale data and return how many rows each rule touched.

    - guests unseen for GUEST_RETENTION_DAYS: deleted (FK cascades remove sessions, messages, reports, resumes, counters)
    - "active" interviews older than ABANDON_AFTER_DAYS: marked abandoned
    - registered users' interviews older than SESSION_RETENTION_DAYS (0 = keep): deleted
    - daily usage counters older than a week: deleted (only today's matter for limits)
    """
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    stats = {"guests": 0, "abandoned": 0, "sessions": 0, "counters": 0}

    if s.GUEST_RETENTION_DAYS > 0:
        cutoff = now - timedelta(days=s.GUEST_RETENTION_DAYS)
        res = await db.execute(delete(User).where(User.is_guest.is_(True), User.last_seen_at < cutoff))
        stats["guests"] = res.rowcount or 0

    if s.ABANDON_AFTER_DAYS > 0:
        cutoff = now - timedelta(days=s.ABANDON_AFTER_DAYS)
        res = await db.execute(
            update(InterviewSession)
            .where(InterviewSession.status == SessionStatus.active.value, InterviewSession.created_at < cutoff)
            .values(status=SessionStatus.abandoned.value)
        )
        stats["abandoned"] = res.rowcount or 0

    if s.SESSION_RETENTION_DAYS > 0:
        cutoff = now - timedelta(days=s.SESSION_RETENTION_DAYS)
        res = await db.execute(delete(InterviewSession).where(InterviewSession.created_at < cutoff))
        stats["sessions"] = res.rowcount or 0

    counter_cutoff: date = (now - timedelta(days=COUNTER_RETENTION_DAYS)).date()
    res = await db.execute(delete(UsageCounter).where(UsageCounter.day < counter_cutoff))
    stats["counters"] = res.rowcount or 0

    await db.commit()
    return stats


async def cleanup_loop() -> None:
    """Run purge_stale shortly after startup, then every CLEANUP_INTERVAL_HOURS. Never raises."""
    await asyncio.sleep(FIRST_RUN_DELAY_SECONDS)
    while True:
        try:
            async with get_session_factory()() as db:
                stats = await purge_stale(db)
            logger.info("cleanup", extra=stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(max(1, get_settings().CLEANUP_INTERVAL_HOURS) * 3600)
