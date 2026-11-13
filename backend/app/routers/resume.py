import re
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.config import get_settings
from app.core.errors import AppError
from app.core.limits import check_resume_limit
from app.database import SessionFactory, get_session_factory
from app.dependencies import CurrentUser, DbSession
from app.models import Resume
from app.services.resume import SUMMARY_FAILED, check_pdf_bytes, extract_text, summarize_resume

router = APIRouter(prefix="/resume", tags=["resume"])
Factory = Annotated[SessionFactory, Depends(get_session_factory)]

_PDF_TYPES = {"application/pdf", "application/x-pdf"}
_BAD_NAME_CHARS = re.compile(r"[^\w .()\-]+")


class ResumeOut(BaseModel):
    resume_id: uuid.UUID
    filename: str
    pages: int | None = None
    ready: bool = False  # false while the summary is still being written
    failed: bool = False  # true when no summary could be made (the interview still works, just not personalised)


def _safe_filename(name: str | None) -> str:
    cleaned = _BAD_NAME_CHARS.sub("", (name or "resume.pdf").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip()
    return (cleaned or "resume.pdf")[:200]


@router.post("", response_model=ResumeOut, status_code=201)
async def upload_resume(
    user: CurrentUser, db: DbSession, factory: Factory, background: BackgroundTasks, file: UploadFile = File(...)
) -> ResumeOut:
    await check_resume_limit(db, user)  # before reading the body
    if (file.content_type or "").split(";")[0].strip().lower() not in _PDF_TYPES:
        raise AppError("invalid_file_type", "Please upload a PDF file.", 415)
    max_bytes = get_settings().MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AppError("payload_too_large", f"The file is larger than {get_settings().MAX_UPLOAD_MB} MB.", 413)
    check_pdf_bytes(data)
    text, pages = await extract_text(data)

    row = Resume(user_id=user.id, filename=_safe_filename(file.filename), extracted_text=text, summary="")
    db.add(row)
    await db.commit()
    background.add_task(summarize_resume, row.id, factory)
    return ResumeOut(resume_id=row.id, filename=row.filename, pages=pages)


async def _owned(db: DbSession, user: CurrentUser, resume_id: uuid.UUID) -> Resume:
    row = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if row is None:
        raise AppError("not_found", "Resume not found.", 404)
    return row


@router.get("/{resume_id}", response_model=ResumeOut)
async def get_resume(resume_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ResumeOut:
    """Polled by the setup page until the summary is ready."""
    row = await _owned(db, user, resume_id)
    return ResumeOut(
        resume_id=row.id, filename=row.filename, ready=bool(row.summary), failed=row.summary == SUMMARY_FAILED
    )


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(resume_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await _owned(db, user, resume_id)
    await db.execute(delete(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    await db.commit()
    return Response(status_code=204)
