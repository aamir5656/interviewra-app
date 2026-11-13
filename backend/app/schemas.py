import re
import uuid
from datetime import datetime

from typing import Any

from app.roles import canonical_role
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import InterviewType, Level

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 320 or not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v


class _EmailIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


def _check_password(v: str) -> str:
    if "\x00" in v:
        raise ValueError("Password contains invalid characters")
    if len(v.encode("utf-8")) > 72:  # bcrypt only uses the first 72 bytes
        raise ValueError("Password is too long (max 72 bytes)")
    return v


class RegisterRequest(_EmailIn):
    password: str = Field(min_length=8, max_length=72)
    display_name: str

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _check_password(v)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 50:
            raise ValueError("Display name must be 1 to 50 characters")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        return _check_password(v)


class LoginRequest(_EmailIn):
    password: str = Field(min_length=1, max_length=128)
    merge_guest: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    display_name: str
    role: str
    is_guest: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- interviews (Part 4) ----------


def _stripped(v: str, lo: int, hi: int, label: str) -> str:
    v = v.strip()
    if not lo <= len(v) <= hi:
        raise ValueError(f"{label} must be {lo} to {hi} characters")
    return v


class InterviewCreate(BaseModel):
    role_name: str
    level: Level
    interview_type: InterviewType
    question_count: int = Field(default=5, ge=3, le=10)
    resume_id: uuid.UUID | None = None

    @field_validator("role_name")
    @classmethod
    def _role_name(cls, v: str) -> str:
        role = canonical_role(v)
        if role is None:
            raise ValueError("Please choose a role from the list.")
        return role


class AnswerCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        return _stripped(v, 1, 4000, "Answer")


class InterviewRename(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _stripped(v, 1, 80, "Title")


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    role_name: str
    level: str
    interview_type: str
    question_count: int
    current_question_index: int
    status: str
    created_at: datetime
    ended_at: datetime | None


class SessionList(BaseModel):
    items: list[SessionOut]
    total: int
    limit: int
    offset: int


# ---------- report (Part 5) ----------

_MAX_TEXT = 1500
_MAX_LIST_ITEMS = 10


def clamp_score(v: Any) -> int:
    """Any number-like value -> int in 0..100 (raises ValueError for non-numbers)."""
    if isinstance(v, bool):
        raise ValueError("score must be a number")
    return max(0, min(100, int(round(float(v)))))


def _clean_text(v: Any) -> str:
    return (v if isinstance(v, str) else str(v if v is not None else "")).strip()[:_MAX_TEXT]


def _clean_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        raise ValueError("must be a list")
    return [t for t in (_clean_text(x) for x in v) if t][:_MAX_LIST_ITEMS]


class CategoryScores(BaseModel):
    technical_accuracy: int
    communication: int
    depth: int
    problem_solving: int

    @field_validator("*", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> int:
        return clamp_score(v)


def _flag(v: Any) -> bool:
    """Model output -> bool: real booleans pass, null/missing means False, 'true'/'yes'/1 mean True."""
    if isinstance(v, bool):
        return v
    return str(v if v is not None else "").strip().lower() in ("true", "yes", "1")


class PerQuestion(BaseModel):
    question: str
    answer_summary: str = ""
    score: int
    feedback: str = ""
    better_answer_hint: str = ""
    critical_mistake: bool = False  # the answer contained a harmful claim (the score is capped in code)
    needed_prompting: bool = False  # the answer only became correct after a follow-up or hint
    mistakes: list[str] = []  # the harmful claims behind a critical_mistake (required when it is set)

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> int:
        return clamp_score(v)

    @field_validator("critical_mistake", "needed_prompting", mode="before")
    @classmethod
    def _flags(cls, v: Any) -> bool:
        return _flag(v)

    @field_validator("mistakes", mode="before")
    @classmethod
    def _mistakes(cls, v: Any) -> list[str]:
        return _clean_list(v) if isinstance(v, list) else []

    @field_validator("question", "answer_summary", "feedback", "better_answer_hint", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return _clean_text(v)


class Report(BaseModel):
    """Contract report JSON (+ `is_fallback`, true when the AI report could not be produced)."""

    overall_score: int
    category_scores: CategoryScores
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    per_question: list[PerQuestion]
    improvement_tips: list[str]
    recommended_topics: list[str]
    is_fallback: bool = False
    verdict: str = ""  # derived in code from overall_score and the critical flag, never trusted from the model
    has_critical: bool = False  # true when any question has a critical mistake

    @field_validator("overall_score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> int:
        return clamp_score(v)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> str:
        return _clean_text(v)

    @field_validator("strengths", "weaknesses", "improvement_tips", "recommended_topics", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> list[str]:
        return _clean_list(v)

    @field_validator("per_question", mode="after")
    @classmethod
    def _cap_questions(cls, v: list[PerQuestion]) -> list[PerQuestion]:
        return v[:20]


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    feedback: Report | None = None
    ready_to_end: bool = False
