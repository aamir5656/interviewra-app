import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.services.question_text import question_of
from app.services.resume import SUMMARY_FAILED
from app.models import InterviewSession, Message, MessageRole, Resume, User
from app.services.llm.base import BEGIN_TURN_TEXT, ChatMessage
from app.services.memory import compact_profile, load_profile, split_summary
from app.services.prompts import fence_safe, render

CHAT_ROLES = (MessageRole.user.value, MessageRole.assistant.value)


def wrap_answer(text: str) -> str:
    """Candidate text is DATA: it is passed inside clear delimiters and cannot close them."""
    return f"<candidate_answer>\n{fence_safe(text)}\n</candidate_answer>"


def new_message(session_id: uuid.UUID, role: MessageRole, content: str) -> Message:
    # Explicit timestamp: DB now() is the transaction start time and would not order messages within one transaction.
    return Message(session_id=session_id, role=role.value, content=content, created_at=datetime.now(timezone.utc))


async def get_owned_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> InterviewSession:
    """Load a session that belongs to `user`, else 404 (never reveal that another user's session exists)."""
    session = await db.scalar(
        select(InterviewSession).where(InterviewSession.id == session_id, InterviewSession.user_id == user.id)
    )
    if session is None:
        raise AppError("not_found", "Interview not found.", 404)
    return session


async def session_ready_to_end(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """True once the interviewer called end_interview (recorded in the last assistant message's tool_calls)."""
    calls = await db.scalar(
        select(Message.tool_calls)
        .where(Message.session_id == session_id, Message.role == MessageRole.assistant.value)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return any(c.get("name") == "end_interview" for c in (calls or []) if isinstance(c, dict))


MAX_FOLLOWUPS_PER_QUESTION = 1  # one follow-up (or hint + retry) per main question, then the server moves on


def _has_call(calls: object, name: str) -> bool:
    return any(isinstance(c, dict) and c.get("name") == name for c in (calls or []))  # type: ignore[union-attr]


async def followups_used(db: AsyncSession, session_id: uuid.UUID) -> int:
    """Interviewer turns since the last main question was asked (follow-ups, hints, repeats).

    A main question is an interviewer message whose turn counted a `get_next_topic` call. This reads the stored
    messages, so it needs no extra column and cannot drift from what was really said.
    """
    rows = (
        await db.scalars(
            select(Message.tool_calls)
            .where(Message.session_id == session_id, Message.role == MessageRole.assistant.value)
            .order_by(Message.created_at)
        )
    ).all()
    used = 0
    for calls in rows:
        used = 0 if _has_call(calls, "get_next_topic") else used + 1
    return used


async def current_question(db: AsyncSession, session_id: uuid.UUID) -> str:
    """The exact text of the main question on the table (saved with the last main-question message)."""
    row = (await db.execute(
        select(Message.content, Message.tool_calls)
        .where(Message.session_id == session_id, Message.role == MessageRole.assistant.value,
               Message.tool_calls.contains([{"name": "get_next_topic"}]))
        .order_by(Message.created_at.desc()).limit(1)
    )).first()
    return question_of(row.content, row.tool_calls) if row else ""


async def session_cv_relevance(db: AsyncSession, session_id: uuid.UUID) -> tuple[str, str, str]:
    """(relevance, level_fit) decided when the interview started; it is stored on the opening interviewer message."""
    first = await db.scalar(
        select(Message.tool_calls)
        .where(Message.session_id == session_id, Message.role == MessageRole.assistant.value)
        .order_by(Message.created_at).limit(1)
    )
    for c in first or []:
        if isinstance(c, dict) and c.get("name") == "cv_relevance":
            a = c.get("arguments") or {}
            return str(a.get("relevance", "none")), str(a.get("level_fit", "match")), str(a.get("cv_field", ""))
    return "none", "match", ""


async def build_messages(
    db: AsyncSession, session: InterviewSession, new_answer: str | None, *, wrap_up: bool = False,
    final_check: bool = False, next_topic: dict | None = None, answer_flag: str = "ok", must_ask: bool = False,
    qtype: str | None = None, repeat: bool = False, cv: tuple[str, str, str] | None = None, mistake_area: str = "",
) -> tuple[str, list[ChatMessage]]:
    """System prompt (interviewer.md + session notes) and the last HISTORY_WINDOW messages plus the new answer.

    The system prompt carries the rolling summary of older turns and a short `candidate_profile`:
    this session's resume summary (everyone) and long-term memory (registered users only).
    `new_answer=None` builds the opening turn (no candidate message yet).
    """
    resume_summary = ""
    if session.resume_id is not None:
        resume_summary = await db.scalar(
            select(Resume.summary).where(Resume.id == session.resume_id, Resume.user_id == session.user_id)
        ) or ""
    user = await db.get(User, session.user_id)
    memory = compact_profile(await load_profile(db, user.id)) if user is not None and not user.is_guest else {}
    profile: dict[str, object] = {}
    relevance, level_fit, cv_field = cv if cv is not None else await session_cv_relevance(db, session.id)
    if resume_summary and resume_summary != SUMMARY_FAILED and relevance in ("relevant", "partly"):
        profile["resume_summary"] = resume_summary  # a CV for another role is never shown to the interviewer
    if memory:
        profile["past_sessions"] = memory
    variables = dict(
        role_name=session.role_name,
        level=session.level,
        interview_type=session.interview_type,
        question_count=session.question_count,
        current_question_index=session.current_question_index,
        covered_topics=list(session.covered_topics or []),
        candidate_profile=profile,
        cv_mode=relevance, cv_level_fit=level_fit,
    )
    _, rolling = split_summary(session.rolling_summary)
    system = render("interviewer", **variables) + "\n\n" + render(
        "turn_notes", wrap_up=wrap_up, final_check=final_check, rolling_summary=rolling, next_topic=next_topic, opening=new_answer is None,
        question_count=session.question_count, answer_flag=answer_flag, must_ask=must_ask, qtype=qtype,
        cv_mode=relevance, cv_field=cv_field, role_name=session.role_name, repeat=repeat, mistake_area=mistake_area,
        cv_hook=bool(next_topic and profile.get("resume_summary") and relevance == "relevant" and next_topic.get("type") != "hr"),
    )

    rows = (
        await db.scalars(
            select(Message)
            .where(Message.session_id == session.id, Message.role.in_(CHAT_ROLES))
            .order_by(Message.created_at.desc())
            .limit(get_settings().HISTORY_WINDOW)
        )
    ).all()
    history = [
        ChatMessage(role=m.role, content=wrap_answer(m.content) if m.role == MessageRole.user.value else m.content)
        for m in reversed(rows)
    ]
    if history and history[0].role == MessageRole.assistant.value:
        history.insert(0, ChatMessage(role="user", content=BEGIN_TURN_TEXT))  # providers want a user turn first
    if new_answer is not None:
        history.append(ChatMessage(role="user", content=wrap_answer(new_answer)))
    return system, history
