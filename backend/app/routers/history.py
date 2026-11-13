import uuid

from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, func, select

from app.core.errors import AppError
from app.dependencies import CurrentUser, DbSession
from app.models import Feedback, InterviewSession, Message
from app.schemas import InterviewRename, MessageOut, SessionDetail, SessionList, SessionOut
from app.services.conversation import CHAT_ROLES, get_owned_session, session_ready_to_end
from app.services.evaluator import from_feedback

router = APIRouter(prefix="/interviews", tags=["history"])


@router.get("", response_model=SessionList)
async def list_interviews(
    user: CurrentUser, db: DbSession, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)
) -> SessionList:
    total = await db.scalar(select(func.count()).select_from(InterviewSession).where(InterviewSession.user_id == user.id))
    rows = (
        await db.scalars(
            select(InterviewSession)
            .where(InterviewSession.user_id == user.id)
            .order_by(InterviewSession.created_at.desc(), InterviewSession.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return SessionList(items=[SessionOut.model_validate(r) for r in rows], total=total or 0, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_interview(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SessionDetail:
    session = await get_owned_session(db, user, session_id)
    messages = (
        await db.scalars(
            select(Message)
            .where(Message.session_id == session.id, Message.role.in_(CHAT_ROLES))
            .order_by(Message.created_at)
        )
    ).all()
    fb = await db.scalar(select(Feedback).where(Feedback.session_id == session.id))
    return SessionDetail(
        **SessionOut.model_validate(session).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
        feedback=from_feedback(fb) if fb is not None else None,
        ready_to_end=await session_ready_to_end(db, session.id),
    )


@router.patch("/{session_id}", response_model=SessionOut)
async def rename_interview(session_id: uuid.UUID, body: InterviewRename, user: CurrentUser, db: DbSession) -> SessionOut:
    session = await get_owned_session(db, user, session_id)
    session.title = body.title
    await db.commit()
    return SessionOut.model_validate(session)


@router.delete("/{session_id}", status_code=204)
async def delete_interview(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    result = await db.execute(
        delete(InterviewSession).where(InterviewSession.id == session_id, InterviewSession.user_id == user.id)
    )
    if result.rowcount == 0:
        raise AppError("not_found", "Interview not found.", 404)
    await db.commit()
    return Response(status_code=204)
