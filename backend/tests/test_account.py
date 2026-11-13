import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import ALGORITHM, create_access_token
from app.models import InterviewSession, UsageCounter, User
from app.services.cleanup import purge_stale
from tests.conftest import bearer

API = "/api/v1/auth"
PW = "correct-horse-battery"
NEW_PW = "another-long-password"


async def _account(client: AsyncClient) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(f"{API}/register", json={"email": email, "password": PW, "display_name": "Ada"})
    assert r.status_code == 201
    return {**r.json(), "email": email}


def _expired(user_id: str, role: str, ago: timedelta, pv: str | None = None) -> str:
    claims: dict = {"sub": user_id, "role": role, "exp": datetime.now(timezone.utc) - ago}
    if pv:
        claims["pv"] = pv
    return jwt.encode(claims, get_settings().SECRET_KEY, algorithm=ALGORITHM)


# ---------- token refresh ----------


async def test_refresh_returns_a_working_token(client: AsyncClient) -> None:
    acc = await _account(client)
    r = await client.post(f"{API}/refresh", headers=bearer(acc["access_token"]))
    assert r.status_code == 200 and r.json()["user"]["id"] == acc["user"]["id"]
    assert (await client.get(f"{API}/me", headers=bearer(r.json()["access_token"]))).status_code == 200


async def test_refresh_accepts_recently_expired_token(client: AsyncClient) -> None:
    acc = await _account(client)
    old = _expired(acc["user"]["id"], "user", timedelta(hours=2), pv=jwt.decode(acc["access_token"], options={"verify_signature": False})["pv"])
    assert (await client.get(f"{API}/me", headers=bearer(old))).json()["error"]["code"] == "token_expired"
    r = await client.post(f"{API}/refresh", headers=bearer(old))
    assert r.status_code == 200
    assert (await client.get(f"{API}/me", headers=bearer(r.json()["access_token"]))).status_code == 200


async def test_refresh_rejects_token_expired_beyond_grace(client: AsyncClient) -> None:
    acc = await _account(client)
    old = _expired(acc["user"]["id"], "user", timedelta(days=get_settings().REFRESH_GRACE_DAYS + 1))
    r = await client.post(f"{API}/refresh", headers=bearer(old))
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


async def test_refresh_needs_a_valid_token(client: AsyncClient) -> None:
    assert (await client.post(f"{API}/refresh")).status_code == 401
    assert (await client.post(f"{API}/refresh", headers=bearer("garbage"))).status_code == 401


async def test_refresh_rereads_role_and_works_for_guests(client: AsyncClient) -> None:
    guest = (await client.post(f"{API}/guest")).json()
    r = await client.post(f"{API}/refresh", headers=bearer(guest["access_token"]))
    assert r.status_code == 200 and r.json()["user"]["is_guest"] is True


# ---------- change password ----------


async def test_change_password_flow(client: AsyncClient) -> None:
    acc = await _account(client)
    old_token = acc["access_token"]
    r = await client.post(
        f"{API}/change-password", json={"current_password": PW, "new_password": NEW_PW}, headers=bearer(old_token)
    )
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    assert (await client.get(f"{API}/me", headers=bearer(new_token))).status_code == 200
    # the old token (and refreshing with it) is dead, the old password no longer logs in
    assert (await client.get(f"{API}/me", headers=bearer(old_token))).status_code == 401
    assert (await client.post(f"{API}/refresh", headers=bearer(old_token))).status_code == 401
    assert (await client.post(f"{API}/login", json={"email": acc["email"], "password": PW})).status_code == 401
    assert (await client.post(f"{API}/login", json={"email": acc["email"], "password": NEW_PW})).status_code == 200


async def test_change_password_wrong_current(client: AsyncClient) -> None:
    acc = await _account(client)
    r = await client.post(
        f"{API}/change-password", json={"current_password": "nope-nope-nope", "new_password": NEW_PW}, headers=bearer(acc["access_token"])
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_password"
    assert (await client.get(f"{API}/me", headers=bearer(acc["access_token"]))).status_code == 200  # still signed in


async def test_change_password_rejects_same_and_invalid(client: AsyncClient) -> None:
    acc = await _account(client)
    h = bearer(acc["access_token"])
    same = await client.post(f"{API}/change-password", json={"current_password": PW, "new_password": PW}, headers=h)
    assert same.status_code == 400 and same.json()["error"]["code"] == "same_password"
    for bad in ("short", "x" * 73, "ab\x00cdefgh"):
        r = await client.post(f"{API}/change-password", json={"current_password": PW, "new_password": bad}, headers=h)
        assert r.status_code == 422


async def test_change_password_requires_a_real_account(client: AsyncClient) -> None:
    body = {"current_password": PW, "new_password": NEW_PW}
    assert (await client.post(f"{API}/change-password", json=body)).status_code == 401
    guest = (await client.post(f"{API}/guest")).json()
    r = await client.post(f"{API}/change-password", json=body, headers=bearer(guest["access_token"]))
    assert r.status_code == 403


def test_legacy_tokens_without_pv_still_work() -> None:
    token = create_access_token(uuid.uuid4(), "user")  # no password_hash -> no pv claim
    assert "pv" not in jwt.decode(token, get_settings().SECRET_KEY, algorithms=[ALGORITHM])


# ---------- cleanup ----------


def _session(user_id: uuid.UUID, age_days: int, status: str = "completed") -> InterviewSession:
    return InterviewSession(
        user_id=user_id, title="t", role_name="Dev", level="junior", interview_type="mixed", status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


async def test_purge_deletes_stale_guests_with_their_data(db: AsyncSession, now: datetime) -> None:
    stale = User(display_name="g", is_guest=True, role="guest", last_seen_at=now - timedelta(days=40))
    fresh = User(display_name="g", is_guest=True, role="guest", last_seen_at=now - timedelta(days=2))
    old_account = User(email=f"{uuid.uuid4().hex[:8]}@example.com", display_name="a", is_guest=False, role="user", last_seen_at=now - timedelta(days=400))
    db.add_all([stale, fresh, old_account])
    await db.flush()
    stale_session = _session(stale.id, 1)
    db.add_all([stale_session, _session(fresh.id, 1)])
    await db.commit()
    stale_id, fresh_id, account_id, stale_sid = stale.id, fresh.id, old_account.id, stale_session.id

    stats = await purge_stale(db, now)
    db.expire_all()

    assert stats["guests"] >= 1
    assert await db.get(User, stale_id) is None
    assert await db.scalar(select(InterviewSession.id).where(InterviewSession.id == stale_sid)) is None
    assert await db.get(User, fresh_id) is not None
    assert await db.get(User, account_id) is not None  # registered accounts are never deleted


async def test_purge_marks_old_active_sessions_abandoned(db: AsyncSession, now: datetime) -> None:
    u = User(display_name="a", is_guest=False, role="user", email=f"{uuid.uuid4().hex[:8]}@example.com")
    db.add(u)
    await db.flush()
    old_active, new_active, old_done = _session(u.id, 10, "active"), _session(u.id, 1, "active"), _session(u.id, 10, "completed")
    db.add_all([old_active, new_active, old_done])
    await db.commit()
    a_id, n_id, d_id = old_active.id, new_active.id, old_done.id

    await purge_stale(db, now)
    db.expire_all()

    assert (await db.get(InterviewSession, a_id)).status == "abandoned"
    assert (await db.get(InterviewSession, n_id)).status == "active"
    assert (await db.get(InterviewSession, d_id)).status == "completed"


async def test_purge_deletes_very_old_sessions_and_counters(db: AsyncSession, now: datetime) -> None:
    s = get_settings()
    u = User(display_name="a", is_guest=False, role="user", email=f"{uuid.uuid4().hex[:8]}@example.com")
    db.add(u)
    await db.flush()
    ancient, recent = _session(u.id, s.SESSION_RETENTION_DAYS + 5), _session(u.id, 30)
    db.add_all([ancient, recent])
    db.add_all([UsageCounter(user_id=u.id, day=date.today() - timedelta(days=30)), UsageCounter(user_id=u.id, day=date.today())])
    await db.commit()
    ancient_id, recent_id, uid = ancient.id, recent.id, u.id

    await purge_stale(db, now)
    db.expire_all()

    assert await db.scalar(select(InterviewSession.id).where(InterviewSession.id == ancient_id)) is None
    assert await db.scalar(select(InterviewSession.id).where(InterviewSession.id == recent_id)) is not None
    days = (await db.scalars(select(UsageCounter.day).where(UsageCounter.user_id == uid))).all()
    assert days == [date.today()]


async def test_retention_zero_keeps_sessions_forever(db: AsyncSession, now: datetime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "SESSION_RETENTION_DAYS", 0)
    u = User(display_name="a", is_guest=False, role="user", email=f"{uuid.uuid4().hex[:8]}@example.com")
    db.add(u)
    await db.flush()
    s = _session(u.id, 2000)
    db.add(s)
    await db.commit()
    sid = s.id
    await purge_stale(db, now)
    db.expire_all()
    assert await db.get(InterviewSession, sid) is not None
