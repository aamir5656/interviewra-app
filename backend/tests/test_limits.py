import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.config import get_settings
from app.core.limits import check_and_increment, check_resume_limit, get_limit
from app.core.ratelimit import limiter
from app.dependencies import CurrentUser, DbSession, require_role
from tests.conftest import bearer

API = "/api/v1/auth"


@pytest.fixture
def probe(app: FastAPI) -> FastAPI:
    @app.post("/_t/interview")
    async def _interview(user: CurrentUser, db: DbSession) -> dict[str, int]:
        return {"count": await check_and_increment(db, user, "interview")}

    @app.post("/_t/resume")
    async def _resume(user: CurrentUser, db: DbSession) -> dict[str, bool]:
        await check_resume_limit(db, user)
        return {"ok": True}

    @app.get("/_t/admin", dependencies=[__import__("fastapi").Depends(require_role("admin"))])
    async def _admin() -> dict[str, bool]:
        return {"ok": True}

    return app


async def test_limit_exceeded_returns_429_with_retry_after(
    client: AsyncClient, probe: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "LIMIT_GUEST_INTERVIEWS_PER_DAY", 2)
    token = (await client.post(f"{API}/guest")).json()["access_token"]
    for expected in (1, 2):
        r = await client.post("/_t/interview", headers=bearer(token))
        assert r.status_code == 200 and r.json()["count"] == expected
    r = await client.post("/_t/interview", headers=bearer(token))
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    err = r.json()["error"]
    assert err["code"] == "rate_limited" and "account" in err["message"] and err["request_id"]


async def test_resume_limit_zero_blocks(client: AsyncClient, probe: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    token = (await client.post(f"{API}/guest")).json()["access_token"]
    assert (await client.post("/_t/resume", headers=bearer(token))).status_code == 200
    monkeypatch.setattr(get_settings(), "LIMIT_GUEST_RESUMES_PER_DAY", 0)
    r = await client.post("/_t/resume", headers=bearer(token))
    assert r.status_code == 429 and r.headers["Retry-After"]


def test_admin_unlimited_and_role_limits() -> None:
    s = get_settings()
    assert get_limit("admin", "message") is None
    assert get_limit("guest", "interview") == s.LIMIT_GUEST_INTERVIEWS_PER_DAY
    assert get_limit("user", "message") == s.LIMIT_USER_MESSAGES_PER_DAY


async def test_require_role_forbids_non_admin(client: AsyncClient, probe: FastAPI) -> None:
    token = (await client.post(f"{API}/guest")).json()["access_token"]
    r = await client.get("/_t/admin", headers=bearer(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


async def test_ip_rate_limit_uses_contract_error_shape(client: AsyncClient) -> None:
    limiter.enabled = True
    limiter.reset()
    body = {"email": "nobody@example.com", "password": "whatever"}
    codes = [(await client.post(f"{API}/login", json=body)).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    r = await client.post(f"{API}/login", json=body)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"
