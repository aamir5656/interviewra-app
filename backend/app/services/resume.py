"""Resume handling: PDF validation, text extraction (pypdf) and the background summary."""
import asyncio
import io
import json
import logging
import re
import uuid
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import select

from app.core.errors import AppError
from app.database import SessionFactory, async_session_factory
from app.models import Resume
from app.services.llm import get_provider
from app.services.llm.base import ChatMessage, LLMProvider
from app.services.prompts import render
from app.services.reply_checks import INSTRUCTION

logger = logging.getLogger("app.resume")

PDF_MAGIC = b"%PDF-"
MAX_PAGES = 15
MAX_TEXT_CHARS = 30_000
PROMPT_TEXT_CHARS = 12_000  # only this much of the resume text is sent to the model
SUMMARY_FAILED = "{}"  # stored when summarising failed, so the client stops waiting
_LISTS = {"skills": (25, 60), "experience": (6, 200), "projects": (5, 200), "education": (3, 150)}  # (max items, max chars)


def check_pdf_bytes(data: bytes) -> None:
    """Magic bytes must say PDF, whatever the client claimed."""
    if not data.startswith(PDF_MAGIC):
        raise AppError("invalid_file_type", "That file is not a valid PDF.", 415)


def _extract_sync(data: bytes) -> tuple[str, int]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AppError("invalid_pdf", "Password-protected PDFs are not supported.", 422)
        pages = len(reader.pages)
        if pages > MAX_PAGES:
            raise AppError("pdf_too_long", f"Please upload a resume of at most {MAX_PAGES} pages.", 422)
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            parts.append(text)
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                break
    except AppError:
        raise
    except (PyPdfError, ValueError, KeyError, RecursionError, OSError):
        raise AppError("invalid_pdf", "We could not read that PDF.", 422) from None
    text = "\n".join(p for p in parts if p).replace("\x00", "")[:MAX_TEXT_CHARS]
    if len(text.strip()) < 20:
        raise AppError("no_text", "No readable text found. Scanned or image-only PDFs are not supported.", 422)
    return text, pages


async def extract_text(data: bytes) -> tuple[str, int]:
    """(text, page_count). pypdf is blocking, so it runs in a worker thread."""
    return await asyncio.to_thread(_extract_sync, data)


def clean_summary(raw: dict[str, Any]) -> dict[str, list[str]]:
    """Keep only the four expected string lists, clipped to sane sizes."""
    out: dict[str, list[str]] = {}
    for key, (max_items, max_chars) in _LISTS.items():
        value = raw.get(key)
        items = value if isinstance(value, list) else []
        out[key] = [str(i).strip()[:max_chars] for i in items if isinstance(i, (str, int, float)) and str(i).strip()
                    and not INSTRUCTION.search(str(i))][:max_items]  # an instruction hidden in the CV is dropped
    return out


async def summarize_resume(
    resume_id: uuid.UUID, factory: SessionFactory | None = None, provider: LLMProvider | None = None
) -> None:
    """Background task: store the JSON summary on the resume row. Never raises; failure stores SUMMARY_FAILED."""
    summary = SUMMARY_FAILED
    try:
        async with (factory or async_session_factory)() as s:
            text = await s.scalar(select(Resume.extracted_text).where(Resume.id == resume_id))
        if text:
            system = render("resume_summary", resume_text=text[:PROMPT_TEXT_CHARS])
            data = await (provider or get_provider()).chat_json(
                system, [ChatMessage(role="user", content="Summarize the resume now.")]
            )
            cleaned = clean_summary(data)
            if any(cleaned.values()):
                summary = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        logger.warning("resume_summary_failed", exc_info=True)
    try:
        async with (factory or async_session_factory)() as s:
            row = await s.get(Resume, resume_id)
            if row is not None:
                row.summary = summary
                await s.commit()
    except Exception:  # noqa: BLE001
        logger.warning("resume_summary_save_failed", exc_info=True)


CV_RELEVANCE = ("relevant", "partly", "not_relevant")


def has_cv_content(summary: str) -> bool:
    """True when the stored summary holds real data (not empty, not SUMMARY_FAILED)."""
    if not summary or summary == SUMMARY_FAILED:
        return False
    try:
        data = json.loads(summary)
    except ValueError:
        return False
    return isinstance(data, dict) and any(data.get(k) for k in _LISTS)


async def assess_relevance(
    role_name: str, level: str, summary: str, provider: LLMProvider | None = None
) -> tuple[str, str, str]:
    """(relevance, level_fit, cv_field) of the CV for the chosen role, decided once per interview.

    Returns ("none", "match") when there is no usable CV. If the model call fails the CV is treated as only
    "partly" relevant, so it is used carefully instead of being trusted or thrown away.
    """
    if not has_cv_content(summary):
        return "none", "match", ""
    try:
        system = render("cv_relevance", role_name=role_name, level=level, summary=summary)
        data = await (provider or get_provider()).chat_json(system, [ChatMessage(role="user", content="Decide now.")])
        relevance = str(data.get("relevance", "")).strip().lower().replace(" ", "_")
        fit = str(data.get("level_fit", "match")).strip().lower()
        field = re.sub(r"[^\w\s\-/&+.#]", "", str(data.get("cv_field", "")))[:40].strip()  # shown to the candidate: keep it plain
        return ((relevance if relevance in CV_RELEVANCE else "partly"),
                (fit if fit in ("match", "higher", "lower") else "match"), field)
    except Exception:  # noqa: BLE001
        logger.warning("cv_relevance_failed", exc_info=True)
        return "partly", "match", ""
