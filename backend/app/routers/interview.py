import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.config import get_settings
from app.core.errors import AppError
from app.core.limits import check_and_increment
from app.core.sse import sse_event, sse_response
from app.database import SessionFactory, get_session_factory
from app.dependencies import CurrentUser, DbSession
from app.models import Feedback, InterviewSession, Message, MessageRole, Resume, SessionStatus, User
from app.schemas import AnswerCreate, InterviewCreate, Report
from app.services.agent import AgentResult, run_agent_turn
from app.services.answer_judge import judge_answer
from app.services.conversation import (
    MAX_FOLLOWUPS_PER_QUESTION, build_messages, current_question, followups_used, get_owned_session, new_message, session_ready_to_end,
)
from app.services.evaluator import (
    answers_by_question, build_transcript, count_main_questions, from_feedback, generate_report, limit_questions,
    injection_question, main_questions, prompted_by_question, to_feedback,
)
from app.services.llm import get_provider
from app.services.llm.base import LLMProvider
from app.services.resume import assess_relevance
from app.services.reply_checks import (
    REPEAT_FLAGS, check_reply, classify_answer, compose_repeat, question_type, sanitize,
)
from app.services.memory import summarize_old_messages, update_long_term_memory
from app.services.prompts import render
from app.services.tools import ToolContext, choose_topic, tool_specs, load_bank

logger = logging.getLogger("app.interview")
router = APIRouter(prefix="/interviews", tags=["interviews"])
Factory = Annotated[SessionFactory, Depends(get_session_factory)]
TITLE_MAX = 80


_TURN_TTL_SECONDS = 120.0
_running_turns: dict[uuid.UUID, float] = {}  # session id -> start time (single process; stale entries expire)


def _begin_turn(session_id: uuid.UUID) -> None:
    """One interviewer turn per session at a time: a double submit gets 409 instead of a second, duplicate turn."""
    now = time.monotonic()
    if now - _running_turns.get(session_id, -_TURN_TTL_SECONDS) < _TURN_TTL_SECONDS:
        raise AppError("turn_in_progress", "Alex is still answering. Please wait a moment.", 409)
    _running_turns[session_id] = now


def _end_turn(session_id: uuid.UUID) -> None:
    _running_turns.pop(session_id, None)


@dataclass
class _Turn:
    """Progress of one streamed turn, so an aborted stream can undo exactly what it wrote."""

    saved: bool = False


def _tool_context(session: InterviewSession, user: User, factory: SessionFactory) -> ToolContext:
    return ToolContext(
        factory=factory, session_id=session.id, user_id=user.id, is_registered=not user.is_guest,
        role_name=session.role_name, level=session.level, interview_type=session.interview_type,
        question_count=session.question_count,
    )


async def _save_reply(
    factory: SessionFactory, session_id: uuid.UUID, text: str, tool_calls: list[dict] | None
) -> uuid.UUID:
    """Store the assistant message (with the tool calls of this turn, e.g. end_interview). Returns its id."""
    async with factory() as s:
        msg = new_message(session_id, MessageRole.assistant, text)
        msg.tool_calls = tool_calls or None
        s.add(msg)
        await s.commit()
        return msg.id


async def _restore_progress(factory: SessionFactory, session_id: uuid.UUID, covered: list, index: int) -> None:
    async with factory() as s:
        await s.execute(
            update(InterviewSession).where(InterviewSession.id == session_id)
            .values(covered_topics=covered, current_question_index=index)
        )
        await s.commit()


def _clean_title(raw: str) -> str:
    first = (raw.strip().splitlines() or [""])[0]
    return re.sub(r"[\s.!?:;,]+$", "", first.strip().strip("\"'`*# ")).strip()[:TITLE_MAX]


async def _generate_title(
    factory: SessionFactory, provider: LLMProvider, session_id: uuid.UUID,
    role_name: str, level: str, interview_type: str, placeholder: str,
) -> None:
    """Background: zero-shot title (title.md). Never fails the request; keeps the placeholder on any problem."""
    try:
        system = render("title", role_name=role_name, level=level, interview_type=interview_type)
        raw = "".join([c async for c in provider.stream_chat(system, [])])
        title = _clean_title(raw)
        if not title:
            return
        async with factory() as s:  # only replace the placeholder, never a title the user already renamed
            await s.execute(
                update(InterviewSession)
                .where(InterviewSession.id == session_id, InterviewSession.title == placeholder)
                .values(title=title)
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.warning("title_generation_failed", exc_info=True)


@router.post("")
async def start_interview(body: InterviewCreate, user: CurrentUser, db: DbSession, factory: Factory) -> StreamingResponse:
    provider = get_provider()  # misconfiguration is a normal HTTP error, before any stream starts
    if body.resume_id is not None:
        owned = await db.scalar(select(Resume.id).where(Resume.id == body.resume_id, Resume.user_id == user.id))
        if owned is None:
            raise AppError("not_found", "Resume not found.", 404)
    await check_and_increment(db, user, "interview")

    placeholder = f"{body.role_name} interview"
    session = InterviewSession(
        user_id=user.id, title=placeholder, role_name=body.role_name, level=body.level.value,
        interview_type=body.interview_type.value, question_count=body.question_count, resume_id=body.resume_id,
        created_at=datetime.now(timezone.utc),  # explicit: DB now() would tie sessions created in one transaction
    )
    db.add(session)
    await db.commit()
    session_id, role_name, level, itype = session.id, session.role_name, session.level, session.interview_type
    ctx = _tool_context(session, user, factory)
    first_topic = await choose_topic(ctx)  # the server picks and counts main question 1; the model only phrases it
    cv = ("none", "match", "")
    if body.resume_id is not None:  # decided once, stored on the opening message, used for the whole interview
        summary = await db.scalar(select(Resume.summary).where(Resume.id == body.resume_id, Resume.user_id == user.id))
        cv = await assess_relevance(role_name, level, summary or "", provider)
        ctx.calls.append({"name": "cv_relevance", "arguments": {"relevance": cv[0], "level_fit": cv[1], "cv_field": cv[2]}})
        logger.info("cv_relevance_decided", extra={"relevance": cv[0], "level_fit": cv[1], "cv_field": cv[2]})
    system, messages = await build_messages(db, session, None, next_topic=first_topic, cv=cv)
    await db.commit()  # release the connection while the model is working
    turn = _Turn()
    result = AgentResult()
    max_steps = get_settings().MAX_AGENT_STEPS

    async def events() -> AsyncIterator[str]:
        yield sse_event("session", {"session_id": str(session_id)})
        tools = tool_specs(wrap_up=False, registered=ctx.is_registered, topic_chosen=True)
        ctx.allowed_tools = frozenset(t.name for t in tools)
        async for ev in run_agent_turn(
            provider, ctx, system, messages, tools, result, max_steps=max_steps,
            check=lambda text, closing: check_reply(text, "ok", closing=closing, must_ask=False,
                                                    need_tags=get_settings().STRICT_QUESTION_TAGS),
            clean=lambda text: sanitize(text, "ok"),
            fallback=f"Hello, I am Alex Morgan, and I will be your interviewer. {first_topic['question_idea']}"
            if first_topic.get("question_idea") else None,
        ):
            yield ev
        message_id = await _save_reply(factory, session_id, result.text, ctx.calls)
        turn.saved = True
        yield sse_event("done", {"message_id": str(message_id), "ready_to_end": ctx.ended})

    async def on_abort() -> None:  # no first question was delivered: remove the empty session
        if not turn.saved:
            async with factory() as s:
                await s.execute(delete(InterviewSession).where(InterviewSession.id == session_id))
                await s.commit()

    title_task = BackgroundTask(_generate_title, factory, provider, session_id, role_name, level, itype, placeholder)
    return sse_response(events(), on_abort, background=title_task)


@router.post("/{session_id}/answer")
async def answer(
    session_id: uuid.UUID, body: AnswerCreate, user: CurrentUser, db: DbSession, factory: Factory
) -> StreamingResponse:
    session = await get_owned_session(db, user, session_id)
    if session.status != SessionStatus.active.value:
        raise AppError("session_not_active", "This interview has already ended.", 409)
    if await session_ready_to_end(db, session_id):
        raise AppError("interview_finished", "This interview is finished. Generate your report.", 409)
    provider = get_provider()
    _begin_turn(session_id)
    try:
        await check_and_increment(db, user, "message")
        return await _answer_turn(session, session_id, body, user, db, factory, provider)
    except BaseException:
        _end_turn(session_id)
        raise


def _topic_text(covered: list[str] | None) -> str:
    """Names and ideas of the topics that were asked: the vocabulary a tip may legitimately use."""
    wanted = {t.lower() for t in covered or []}
    return " ".join(f"{q['topic']} {q.get('question_idea', '')}" for q in load_bank() if q["topic"].lower() in wanted)


async def _answer_turn(
    session: InterviewSession, session_id: uuid.UUID, body: AnswerCreate, user: User, db: AsyncSession,
    factory: SessionFactory, provider: LLMProvider,
) -> StreamingResponse:
    at_last = session.current_question_index >= session.question_count  # the last planned question is on the table
    covered_before, index_before = list(session.covered_topics or []), session.current_question_index
    ctx = _tool_context(session, user, factory)
    used = await followups_used(db, session_id)  # interviewer turns since the last main question was asked
    # The code owns the counter and the end, never the model:
    # - an answer that needs a retry or follow-up (off-topic, vague, wrong, ...) gets exactly one more turn on the SAME
    #   question; a repeat of the question is built in code from the stored text;
    # - every other answer moves on: the server picks and counts the next main question before the model writes;
    # - after the last question the server ends the interview itself, whatever the model says or forgets.
    qtype = question_type(covered_before)
    flag = classify_answer(body.content, qtype)
    area = ""
    stored_question = ""
    if flag == "ok" and used < MAX_FOLLOWUPS_PER_QUESTION and get_settings().ANSWER_JUDGE:
        # No regex can see a wrong or unprofessional answer on every topic, so one small model call judges it. The code
        # (not the model) then forces exactly one follow-up on the same question before the interview moves on.
        stored_question = await current_question(db, session_id)
        flag, area = await judge_answer(
            provider, role_name=session.role_name, level=session.level, qtype=qtype,
            question=stored_question, answer=body.content,
        )
    must_ask = flag != "ok" and used < MAX_FOLLOWUPS_PER_QUESTION
    repeat = must_ask and flag in REPEAT_FLAGS
    wrap_up = at_last and not must_ask
    final_check = at_last and must_ask
    next_topic: dict | None = None
    if not at_last and not must_ask:
        next_topic = await choose_topic(ctx)
    if repeat and not stored_question:
        stored_question = await current_question(db, session_id)
    if repeat:
        fallback = compose_repeat("", stored_question, flag)
    elif next_topic and next_topic.get("question_idea"):
        fallback = f"Let us move on. {next_topic['question_idea']}"
    else:
        fallback = None
    system, messages = await build_messages(
        db, session, body.content, wrap_up=wrap_up, final_check=final_check, next_topic=next_topic,
        answer_flag=flag, must_ask=must_ask, qtype=qtype, repeat=repeat, mistake_area=area,
    )
    new_topic_turn = next_topic is not None  # a turn that moves on: it may not correct the previous answer
    ctx.calls.append({"name": "answer_flag", "arguments": {"flag": flag}})  # stored: the report learns from it which answers needed help
    user_msg = new_message(session_id, MessageRole.user, body.content)
    db.add(user_msg)
    await db.commit()
    user_msg_id = user_msg.id
    turn = _Turn()
    result = AgentResult()
    max_steps = get_settings().MAX_AGENT_STEPS

    async def events() -> AsyncIterator[str]:
        try:
            async for ev in _answer_events():
                yield ev
        finally:
            _end_turn(session_id)

    async def _answer_events() -> AsyncIterator[str]:
        tools = tool_specs(wrap_up=wrap_up, registered=ctx.is_registered, topic_chosen=next_topic is not None or must_ask,
                           allow_end=True)
        if repeat:
            tools = []  # the model only writes the lead-in
        ctx.allowed_tools = frozenset(t.name for t in tools)
        async for ev in run_agent_turn(
            provider, ctx, system, messages, tools, result, max_steps=max_steps, wrap_up=wrap_up,
            check=lambda text, closing: check_reply(
                text, flag, closing=closing, must_ask=must_ask, repeat=repeat, new_topic=new_topic_turn,
                need_tags=new_topic_turn and get_settings().STRICT_QUESTION_TAGS),
            clean=(lambda text: compose_repeat(sanitize(text, flag), stored_question, flag)) if repeat
            else (lambda text: sanitize(text, flag, new_topic=new_topic_turn, closing=wrap_up, answer=body.content,
                                       turn=(next_topic or {}).get("question_number", 0))),
            fallback=fallback,
        ):
            yield ev
        message_id = await _save_reply(factory, session_id, result.text, ctx.calls)
        turn.saved = True
        yield sse_event("done", {"message_id": str(message_id), "ready_to_end": ctx.ended})

    async def on_abort() -> None:  # nothing was stored: undo tool effects and drop the unanswered message
        if not turn.saved:
            await _restore_progress(factory, session_id, covered_before, index_before)
            async with factory() as s:
                await s.execute(delete(Message).where(Message.id == user_msg_id))
                await s.commit()

    return sse_response(events(), on_abort, background=BackgroundTask(summarize_old_messages, session_id, factory, provider))


async def _stored_report(db: DbSession, session_id: uuid.UUID) -> Report | None:
    fb = await db.scalar(select(Feedback).where(Feedback.session_id == session_id))
    return from_feedback(fb) if fb is not None else None


@router.post("/{session_id}/end", response_model=Report)
async def end_interview(
    session_id: uuid.UUID, user: CurrentUser, db: DbSession, factory: Factory, background: BackgroundTasks
) -> Report:
    """Evaluate the interview, store the report and complete the session. Idempotent."""
    session = await get_owned_session(db, user, session_id)
    if (stored := await _stored_report(db, session.id)) is not None:
        return stored
    if session.status == SessionStatus.abandoned.value:
        raise AppError("session_not_active", "This interview was abandoned.", 409)

    sid, uid = session.id, user.id
    role_name, level, itype = session.role_name, session.level, session.interview_type
    planned = session.question_count
    rows = (await db.scalars(select(Message).where(Message.session_id == sid).order_by(Message.created_at))).all()
    transcript = build_transcript(rows, session.question_count)
    asked = count_main_questions(rows)
    await db.commit()  # release the connection during the (slow) model call

    report = limit_questions(
        await generate_report(role_name, level, itype, transcript, answers_by_question(rows), main_questions(rows),
                               prompted_by_question(rows), injection_question(rows), _topic_text(session.covered_topics)), asked
    )

    if 0 < asked < planned and not report.is_fallback:  # ended early: say so, the average covers only what was asked
        note = f"This interview ended after {asked} of {planned} planned questions, so the report covers only those. "
        report = report.model_copy(update={"summary": (note + report.summary)[:1500]})
    db.add(to_feedback(sid, report))
    await db.execute(
        update(InterviewSession)
        .where(InterviewSession.id == sid, InterviewSession.user_id == uid)
        .values(status=SessionStatus.completed.value, ended_at=datetime.now(timezone.utc))
    )
    try:
        await db.commit()
    except IntegrityError:  # a parallel request finished first (feedback.session_id is unique)
        await db.rollback()
        if (stored := await _stored_report(db, sid)) is not None:
            return stored
        raise
    background.add_task(update_long_term_memory, uid, sid, factory)
    return report


@router.get("/{session_id}/report", response_model=Report)
async def get_report(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Report:
    session = await get_owned_session(db, user, session_id)
    report = await _stored_report(db, session.id)
    if report is None:
        raise AppError("report_not_found", "No report yet for this interview.", 404)
    return report
