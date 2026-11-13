from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feedback, InterviewSession
from tests.conftest import bearer

API = "/api/v1"
PW = "correct-horse-1"


async def registered(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await client.post(f"{API}/auth/register", json={"email": email, "password": PW, "display_name": "Ada"})
    assert r.status_code == 201
    return bearer(r.json()["access_token"]), r.json()["user"]["id"]


async def add_report(db: AsyncSession, user_id: str, score: int, days_ago: int, weaknesses: list[str], cats: dict | None = None) -> None:
    s = InterviewSession(user_id=user_id, title="T", role_name="Backend", level="junior", interview_type="technical", status="completed")
    db.add(s)
    await db.flush()
    db.add(
        Feedback(
            session_id=s.id, overall_score=score, weaknesses=weaknesses, summary="x",
            category_scores=cats if cats is not None else {"technical_accuracy": score, "communication": score, "depth": score, "problem_solving": score},
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    await db.flush()


async def test_guest_cannot_see_dashboard(client: AsyncClient) -> None:
    token = (await client.post(f"{API}/auth/guest")).json()["access_token"]
    assert (await client.get(f"{API}/dashboard/stats", headers=bearer(token))).status_code == 403
    assert (await client.get(f"{API}/dashboard/stats")).status_code == 401


async def test_new_user_gets_empty_stats(client: AsyncClient) -> None:
    h, _ = await registered(client, "empty-dash@example.com")
    body = (await client.get(f"{API}/dashboard/stats", headers=h)).json()
    assert body == {"interview_count": 0, "average_score": None, "score_trend": [], "category_averages": {}, "top_weak_topics": []}


async def test_stats_shape_and_values(client: AsyncClient, db: AsyncSession) -> None:
    h, uid = await registered(client, "dash@example.com")
    await add_report(db, uid, 60, 3, ["No trade-offs", "Skipped edge cases"])
    await add_report(db, uid, 80, 2, ["no trade-offs"])
    await add_report(db, uid, 0, 1, [], cats={})  # fallback report: left out of every number
    body = (await client.get(f"{API}/dashboard/stats", headers=h)).json()
    assert set(body) == {"interview_count", "average_score", "score_trend", "category_averages", "top_weak_topics"}
    assert body["interview_count"] == 2 and body["average_score"] == 70.0
    assert [p["score"] for p in body["score_trend"]] == [60, 80]  # oldest first
    assert set(body["score_trend"][0]) == {"date", "score"}
    assert body["category_averages"]["depth"] == 70.0 and len(body["category_averages"]) == 4
    assert body["top_weak_topics"][0] == {"topic": "No trade-offs", "count": 2}  # case-insensitive merge


async def test_stats_only_count_own_reports(client: AsyncClient, db: AsyncSession) -> None:
    a, a_id = await registered(client, "own-a@example.com")
    b, b_id = await registered(client, "own-b@example.com")
    await add_report(db, a_id, 90, 1, ["x"])
    await add_report(db, b_id, 10, 1, ["y"])
    assert (await client.get(f"{API}/dashboard/stats", headers=a)).json()["average_score"] == 90.0
    assert (await client.get(f"{API}/dashboard/stats", headers=b)).json()["average_score"] == 10.0
