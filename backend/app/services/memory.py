import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionFactory, async_session_factory
from app.models import Feedback, InterviewSession, Message, MessageRole, Resume, User, UserMemory
from app.schemas import Report
from app.services.evaluator import build_transcript, from_feedback
from app.services.llm import get_provider
from app.services.llm.base import LLMProvider, strip_thinking
from app.services.prompts import render

logger = logging.getLogger("app.memory")

PROFILE_CAPS = {"strengths": 8, "weak_topics": 8}
SCORE_TREND_LEN = 10
SESSION_IDS_TRACKED = 20
RESUME_CHARS = 600
ITEM_CHARS = 120
PROMPT_TOP = 3
SUMMARY_MIN_NEW = 4  # summarise only when at least this many messages left the history window (saves LLM calls)
SUMMARY_MAX_CHARS = 1500
_CHAT = (MessageRole.user.value, MessageRole.assistant.value)
_MARK = re.compile(r"^\[\[summarized:(\d+)\]\]\n?")


# ---------- long-term memory (registered users only) ----------


def _merge(new: list[str], old: list[str], cap: int) -> list[str]:
    """Newest first, case-insensitive de-duplication, capped."""
    seen: set[str] = set()
    out: list[str] = []
    for item in [*new, *old]:
        text = str(item).strip()[:ITEM_CHARS]
        key = " ".join(text.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:cap]


def merge_profile(
    profile: dict[str, Any], *, session_id: uuid.UUID, report: Report, role_name: str,
    resume_summary: str | None, now: datetime,
) -> dict[str, Any]:
    trend = [*profile.get("score_trend", []), {"score": report.overall_score, "role": role_name[:40], "date": now.date().isoformat()}]
    return {
        "sessions_completed": int(profile.get("sessions_completed", 0)) + 1,
        "strengths": _merge(report.strengths, profile.get("strengths", []), PROFILE_CAPS["strengths"]),
        "weak_topics": _merge(report.recommended_topics, profile.get("weak_topics", []), PROFILE_CAPS["weak_topics"]),
        "score_trend": trend[-SCORE_TREND_LEN:],
        "session_ids": [str(session_id), *profile.get("session_ids", [])][:SESSION_IDS_TRACKED],
        "resume_summary": (resume_summary or profile.get("resume_summary", ""))[:RESUME_CHARS],
    }


def compact_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Short version for prompts and the get_user_memory tool ({} when there is no memory)."""
    if not profile:
        return {}
    out: dict[str, Any] = {
        "sessions_completed": profile.get("sessions_completed", 0),
        "strengths": list(profile.get("strengths", []))[:PROMPT_TOP],
        "weak_topics": list(profile.get("weak_topics", []))[:PROMPT_TOP],
        "recent_scores": [t.get("score") for t in profile.get("score_trend", [])][-5:],
        "resume_summary": str(profile.get("resume_summary", ""))[:300],
    }
    return {k: v for k, v in out.items() if v not in ("", [], None, 0)}


async def load_profile(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    mem = await db.get(UserMemory, user_id)
    return dict(mem.profile) if mem is not None else {}


async def update_long_term_memory(
    user_id: uuid.UUID, session_id: uuid.UUID, factory: SessionFactory | None = None
) -> None:
    """Background task after a report is saved: merge it into user_memory.profile. Guests are skipped. Never raises."""
    try:
        async with (factory or async_session_factory)() as s:
            user = await s.get(User, user_id)
            if user is None or user.is_guest:
                return
            session = await s.scalar(
                select(InterviewSession).where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
            )
            fb = await s.scalar(select(Feedback).where(Feedback.session_id == session_id))
            if session is None or fb is None:
                return
            report = from_feedback(fb)
            mem = await s.get(UserMemory, user_id)
            profile = dict(mem.profile) if mem is not None else {}
            if report.is_fallback or str(session_id) in profile.get("session_ids", []):
                return
            resume_summary = await s.scalar(
                select(Resume.summary).where(Resume.user_id == user_id, Resume.summary != "")
                .order_by(Resume.created_at.desc()).limit(1)
            )
            now = datetime.now(timezone.utc)
            merged = merge_profile(
                profile, session_id=session_id, report=report, role_name=session.role_name,
                resume_summary=resume_summary, now=now,
            )
            if mem is None:
                s.add(UserMemory(user_id=user_id, profile=merged, updated_at=now))
            else:
                mem.profile, mem.updated_at = merged, now
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.warning("long_term_memory_update_failed", exc_info=True)


# ---------- short-term memory: rolling summary ----------


def split_summary(stored: str) -> tuple[int, str]:
    """rolling_summary is stored as '[[summarized:N]]\\n<text>' (N = messages already folded in)."""
    m = _MARK.match(stored or "")
    return (int(m.group(1)), stored[m.end():].strip()) if m else (0, (stored or "").strip())


def join_summary(count: int, text: str) -> str:
    return f"[[summarized:{count}]]\n{text}"


async def summarize_old_messages(
    session_id: uuid.UUID, factory: SessionFactory | None = None, provider: LLMProvider | None = None
) -> None:
    """Background task: fold messages that left the HISTORY_WINDOW into rolling_summary (summarizer.md). Never raises."""
    factory = factory or async_session_factory
    try:
        async with factory() as s:
            session = await s.get(InterviewSession, session_id)
            if session is None:
                return
            msgs = (
                await s.scalars(
                    select(Message).where(Message.session_id == session_id, Message.role.in_(_CHAT))
                    .order_by(Message.created_at)
                )
            ).all()
            done, previous = split_summary(session.rolling_summary)
            upto = len(msgs) - get_settings().HISTORY_WINDOW
            if upto - done < SUMMARY_MIN_NEW:
                return
            turns = build_transcript(msgs[done:upto])
            stored_before = session.rolling_summary
            await s.commit()
        system = render("summarizer", previous_summary=previous, turns=turns)
        provider = provider or get_provider()
        raw = "".join([c async for c in provider.stream_chat(system, [])])
        summary = strip_thinking(raw)[:SUMMARY_MAX_CHARS].strip()
        if not summary:
            return
        async with factory() as s:
            await s.execute(
                update(InterviewSession)
                .where(InterviewSession.id == session_id, InterviewSession.rolling_summary == stored_before)
                .values(rolling_summary=join_summary(upto, summary))
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.warning("summarize_failed", exc_info=True)
