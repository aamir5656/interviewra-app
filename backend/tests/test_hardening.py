"""Part 11: gaps found while reviewing the suite: headers/CORS, production settings, validators, cross-user resume use."""
import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import InterviewSession, Resume
from app.schemas import AnswerCreate, InterviewCreate, InterviewRename, RegisterRequest
from tests.conftest import bearer
from tests.helpers import API, guest, start

PW = "correct-horse-1"


# ---------- headers, CORS, health ----------


async def test_security_headers_and_request_id(client: AsyncClient) -> None:
    r = await client.get(f"{API}/auth/me")  # 401, but every response must carry the headers
    assert r.status_code == 401
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-request-id"] and r.json()["error"]["request_id"] == r.headers["x-request-id"]


async def test_health_is_public_and_cheap(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}  # what the keep-awake ping calls


async def test_cors_allows_only_configured_origins(client: AsyncClient) -> None:
    ok = await client.options(
        f"{API}/interviews",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    evil = await client.options(
        f"{API}/interviews",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers


async def test_oversized_upload_is_cut_off_by_the_body_limit(client: AsyncClient) -> None:
    h = await guest(client)
    big = b"%PDF-" + b"0" * (7 * 1024 * 1024)  # well over MAX_UPLOAD_MB plus multipart overhead
    r = await client.post(f"{API}/resume", files={"file": ("cv.pdf", big, "application/pdf")}, headers=h)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


# ---------- settings ----------


def _settings(**kw: str) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize("key", ["change-me", "change-me-use-python-secrets-token-urlsafe-48", "short", "x" * 31])
def test_production_rejects_weak_secret_key(key: str) -> None:
    with pytest.raises(ValidationError):
        _settings(ENV="production", SECRET_KEY=key)


def test_production_accepts_a_strong_secret_key() -> None:
    s = _settings(ENV="production", SECRET_KEY="a1" * 32)
    assert s.is_production
    assert _settings(ENV="development").is_production is False  # the weak default is fine for local work


def test_neon_connection_string_is_normalised() -> None:
    s = _settings(DATABASE_URL="postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require")
    assert s.DATABASE_URL == "postgresql+asyncpg://u:p@ep-x.neon.tech/db?ssl=require"
    assert _settings(DATABASE_URL="postgres://u:p@h/db").DATABASE_URL.startswith("postgresql+asyncpg://")


def test_cors_origins_are_split_and_trimmed() -> None:
    s = _settings(CORS_ORIGINS="https://app.vercel.app/, http://localhost:3000 ,")
    assert s.cors_origins_list == ["https://app.vercel.app", "http://localhost:3000"]


# ---------- validators ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"password": "short", "display_name": "Ada"},
        {"password": "a" * 73, "display_name": "Ada"},
        {"password": "é" * 40, "display_name": "Ada"},  # 80 bytes: bcrypt would silently truncate
        {"password": "good-password\x00", "display_name": "Ada"},
        {"password": PW, "display_name": "   "},
        {"password": PW, "display_name": "x" * 51},
    ],
)
def test_register_validators_reject(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.co", **kwargs)


def test_email_is_trimmed_lowercased_and_checked() -> None:
    assert RegisterRequest(email="  Ada@Example.COM ", password=PW, display_name="Ada").email == "ada@example.com"
    for bad in ("nope", "a@b", "a b@c.de", "@x.co"):
        with pytest.raises(ValidationError):
            RegisterRequest(email=bad, password=PW, display_name="Ada")


@pytest.mark.parametrize("overrides", [{"role_name": "x"}, {"role_name": "r" * 81}, {"question_count": 2}, {"question_count": 11}, {"level": "god"}, {"interview_type": "x"}])
def test_interview_create_validators_reject(overrides: dict) -> None:
    body = {"role_name": "Backend", "level": "junior", "interview_type": "mixed", "question_count": 5, **overrides}
    with pytest.raises(ValidationError):
        InterviewCreate(**body)


def test_text_fields_are_stripped_and_bounded() -> None:
    assert InterviewRename(title="  Mine  ").title == "Mine"
    assert AnswerCreate(content="  hi \n").content == "hi"
    for bad in ("", "   ", "t" * 81):
        with pytest.raises(ValidationError):
            InterviewRename(title=bad)
    with pytest.raises(ValidationError):
        AnswerCreate(content="a" * 4001)


async def test_rename_validation_over_http(client: AsyncClient, use_fake_llm) -> None:
    use_fake_llm(tool_responses=["Q1?"], texts=["T"])
    h = await guest(client)
    r = await start(client, h)
    sid = r.text.split('"session_id": "')[1].split('"')[0]
    for title in ("", "   ", "t" * 81):
        resp = await client.patch(f"{API}/interviews/{sid}", json={"title": title}, headers=h)
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


# ---------- resumes across accounts ----------


async def _resume_for(db: AsyncSession, user_id: str) -> Resume:
    row = Resume(user_id=uuid.UUID(user_id), filename="cv.pdf", extracted_text="x" * 40, summary='{"skills":["Go"]}')
    db.add(row)
    await db.commit()
    return row


async def _guest_user(client: AsyncClient) -> tuple[dict[str, str], str]:
    body = (await client.post(f"{API}/auth/guest")).json()
    return bearer(body["access_token"]), body["user"]["id"]


async def test_cannot_start_an_interview_with_someone_elses_resume(client: AsyncClient, db: AsyncSession, use_fake_llm) -> None:
    use_fake_llm(tool_responses=["Q1?"], texts=["T"])
    _, owner_id = await _guest_user(client)
    thief, _ = await _guest_user(client)
    resume = await _resume_for(db, owner_id)
    r = await start(client, thief, resume_id=str(resume.id))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_login_merge_also_moves_resumes(client: AsyncClient, db: AsyncSession) -> None:
    email = f"merge-{uuid.uuid4().hex[:8]}@example.com"
    acc = (await client.post(f"{API}/auth/register", json={"email": email, "password": PW, "display_name": "Ada"})).json()["user"]
    g_headers, g_id = await _guest_user(client)
    resume = await _resume_for(db, g_id)
    db.add(InterviewSession(user_id=uuid.UUID(g_id), title="t", role_name="Dev", level="junior", interview_type="mixed"))
    await db.commit()
    r = await client.post(f"{API}/auth/login", json={"email": email, "password": PW, "merge_guest": True}, headers=g_headers)
    assert r.status_code == 200
    moved = await db.scalar(select(Resume.user_id).where(Resume.id == resume.id))
    assert str(moved) == acc["id"]
