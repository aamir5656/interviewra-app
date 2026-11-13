from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import DbSession, require_role
from app.models import Feedback, InterviewSession, Role, User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TREND_POINTS = 30
TOP_WEAK = 5
CATEGORIES = ("technical_accuracy", "communication", "depth", "problem_solving")
_REGISTERED = require_role(Role.user, Role.admin)


class TrendPoint(BaseModel):
    date: datetime
    score: int


class WeakTopic(BaseModel):
    topic: str
    count: int


class DashboardStats(BaseModel):
    interview_count: int  # finished interviews that have a report
    average_score: float | None
    score_trend: list[TrendPoint]  # oldest first, last TREND_POINTS reports
    category_averages: dict[str, float]
    top_weak_topics: list[WeakTopic]


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(db: DbSession, user: User = Depends(_REGISTERED)) -> DashboardStats:
    """Progress numbers for the signed-in registered user (guests get 403). Fallback reports are left out."""
    rows = (
        await db.execute(
            select(Feedback.overall_score, Feedback.category_scores, Feedback.weaknesses, Feedback.created_at, Feedback.summary)
            .join(InterviewSession, InterviewSession.id == Feedback.session_id)
            .where(InterviewSession.user_id == user.id)
            .order_by(Feedback.created_at.asc())
        )
    ).all()
    real = [r for r in rows if r.category_scores]  # fallback reports store no category scores

    cats: dict[str, list[float]] = {c: [] for c in CATEGORIES}
    weak: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for r in real:
        scores: dict[str, Any] = r.category_scores
        for c in CATEGORIES:
            if isinstance(scores.get(c), (int, float)):
                cats[c].append(float(scores[c]))
        for w in r.weaknesses or []:
            if isinstance(w, str) and w.strip():
                key = w.strip().lower()
                weak[key] += 1
                labels.setdefault(key, w.strip())

    return DashboardStats(
        interview_count=len(real),
        average_score=_avg([float(r.overall_score) for r in real]),
        score_trend=[TrendPoint(date=r.created_at, score=r.overall_score) for r in real[-TREND_POINTS:]],
        category_averages={c: v for c in CATEGORIES if (v := _avg(cats[c])) is not None},
        top_weak_topics=[WeakTopic(topic=labels[k], count=n) for k, n in weak.most_common(TOP_WEAK)],
    )
