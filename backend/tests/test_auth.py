import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterviewSession, User
from tests.conftest import bearer

API = "/api/v1/auth"
PW = "correct-horse-battery"


async def _guest(client: AsyncClient) -> dict:
    r = await client.post(f"{API}/guest")
    assert r.status_code == 201
    return r.json()


async def _register(client: AsyncClient, email: str, token: str | None = None, name: str = "Ada") -> "object":
    headers = bearer(token) if token else None
    return await client.post(
        f"{API}/register", json={"email": email, "password": PW, "display_name": name}, headers=headers
    )


def _email() -> str:
    return f"{uuid.uuid4().hex[:10]}@Example.com"


async def test_guest_creation(client: AsyncClient) -> None:
    data = await _guest(client)
    assert data["token_type"] == "bearer"
    assert data["user"]["is_guest"] is True and data["user"]["role"] == "guest"
    assert data["user"]["display_name"] == "Guest" and data["user"]["email"] is None
    me = await client.get(f"{API}/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200 and me.json()["id"] == data["user"]["id"]


async def test_guest_upgrade_keeps_same_user_id(client: AsyncClient) -> None:
    guest = await _guest(client)
    email = _email()
    r = await _register(client, email, guest["access_token"], name="  Ada  ")
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["id"] == guest["user"]["id"]
    assert user["is_guest"] is False and user["role"] == "user"
    assert user["email"] == email.lower() and user["display_name"] == "Ada"
    me = await client.get(f"{API}/me", headers=bearer(r.json()["access_token"]))
    assert me.json()["role"] == "user"


async def test_register_without_token_creates_new_user(client: AsyncClient) -> None:
    r = await _register(client, _email())
    assert r.status_code == 201 and r.json()["user"]["role"] == "user"


async def test_duplicate_email_rejected_case_insensitive(client: AsyncClient) -> None:
    email = _email()
    assert (await _register(client, email)).status_code == 201
    r = await _register(client, email.upper())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_validation_errors(client: AsyncClient) -> None:
    r = await client.post(f"{API}/register", json={"email": "nope", "password": "short", "display_name": "  "})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_login_wrong_password_and_me_requires_token(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    bad = await client.post(f"{API}/login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    assert (await client.get(f"{API}/me")).status_code == 401
    assert (await client.get(f"{API}/me", headers=bearer("garbage"))).json()["error"]["code"] == "invalid_token"


async def test_login_returns_token(client: AsyncClient) -> None:
    email = _email()
    reg = (await _register(client, email)).json()
    r = await client.post(f"{API}/login", json={"email": email.upper(), "password": PW})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == reg["user"]["id"]
    assert (await client.get(f"{API}/me", headers=bearer(r.json()["access_token"]))).status_code == 200


async def test_merge_guest_on_login(client: AsyncClient, db: AsyncSession) -> None:
    email = _email()
    account = (await _register(client, email)).json()["user"]
    guest = await _guest(client)
    guest_id = uuid.UUID(guest["user"]["id"])
    db.add(InterviewSession(user_id=guest_id, title="t", role_name="Dev", level="junior", interview_type="mixed"))
    await db.commit()

    r = await client.post(
        f"{API}/login", json={"email": email, "password": PW, "merge_guest": True}, headers=bearer(guest["access_token"])
    )
    assert r.status_code == 200 and r.json()["user"]["id"] == account["id"]
    owners = (await db.scalars(select(InterviewSession.user_id))).all()
    assert uuid.UUID(account["id"]) in owners
    assert await db.scalar(select(User).where(User.id == guest_id)) is None
    assert (await client.get(f"{API}/me", headers=bearer(guest["access_token"]))).status_code == 401


async def test_login_without_merge_keeps_guest(client: AsyncClient, db: AsyncSession) -> None:
    email = _email()
    await _register(client, email)
    guest = await _guest(client)
    r = await client.post(f"{API}/login", json={"email": email, "password": PW}, headers=bearer(guest["access_token"]))
    assert r.status_code == 200
    assert await db.scalar(select(User).where(User.id == uuid.UUID(guest["user"]["id"]))) is not None
