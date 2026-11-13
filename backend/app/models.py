from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, enum.Enum):
    guest = "guest"
    user = "user"
    admin = "admin"


class Level(str, enum.Enum):
    intern = "intern"
    junior = "junior"
    mid = "mid"
    senior = "senior"


class InterviewType(str, enum.Enum):
    technical = "technical"
    hr = "hr"
    behavioral = "behavioral"
    mixed = "mixed"


class SessionStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    abandoned = "abandoned"


class MessageRole(str, enum.Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


def _in(col: str, enum_cls: type[enum.Enum]) -> str:
    return f"{col} IN ({', '.join(repr(e.value) for e in enum_cls)})"


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", Role), name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)  # store lowercased
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default=Role.guest.value, server_default=Role.guest.value)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at: Mapped[datetime] = _ts()

    sessions: Mapped[list[InterviewSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    extracted_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint(_in("level", Level), name="level"),
        CheckConstraint(_in("interview_type", InterviewType), name="interview_type"),
        CheckConstraint(_in("status", SessionStatus), name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    role_name: Mapped[str] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(10))
    interview_type: Mapped[str] = mapped_column(String(12))
    question_count: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    current_question_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    covered_topics: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    rolling_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(
        String(10), default=SessionStatus.active.value, server_default=SessionStatus.active.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Message.created_at",
    )
    feedback: Mapped[Feedback | None] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (CheckConstraint(_in("role", MessageRole), name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    tool_calls: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    session: Mapped[InterviewSession] = relationship(back_populates="messages")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True
    )
    overall_score: Mapped[int] = mapped_column(Integer)
    category_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    strengths: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    weaknesses: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    per_question: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    tips: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    session: Mapped[InterviewSession] = relationship(back_populates="feedback")


class UserMemory(Base):
    __tablename__ = "user_memory"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    interviews_started: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
