import pytest
from httpx import AsyncClient

from app.config import get_settings
from tests.helpers import API, guest, parse_sse, start
from tests.pdfs import make_pdf

SUMMARY = {
    "skills": ["Python", "FastAPI"],
    "experience": ["Backend Dev at Acme (2023-2024): built billing APIs"],
    "projects": ["Interviewra: AI mock interview coach"],
    "education": ["BSc Computer Science, Example University (2023)"],
}


async def upload(client: AsyncClient, h: dict, data: bytes, content_type: str = "application/pdf", name: str = "cv.pdf"):
    return await client.post(f"{API}/resume", files={"file": (name, data, content_type)}, headers=h)


async def test_rejects_wrong_content_type(client: AsyncClient) -> None:
    h = await guest(client)
    r = await upload(client, h, make_pdf(), content_type="text/plain", name="cv.txt")
    assert r.status_code == 415 and r.json()["error"]["code"] == "invalid_file_type"


async def test_rejects_magic_byte_mismatch(client: AsyncClient) -> None:
    h = await guest(client)
    r = await upload(client, h, b"MZ this is an executable pretending to be a pdf" * 10)
    assert r.status_code == 415 and r.json()["error"]["code"] == "invalid_file_type"


async def test_rejects_oversize(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_MB", 0)
    h = await guest(client)
    r = await upload(client, h, make_pdf())
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_rejects_pdf_without_text(client: AsyncClient) -> None:
    h = await guest(client)
    r = await upload(client, h, make_pdf(" "))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_text"


async def test_resume_limit_exceeded(client: AsyncClient, use_fake_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_llm(jsons=[SUMMARY])
    h = await guest(client)
    assert (await upload(client, h, make_pdf())).status_code == 201  # guests may upload 1 per day by default
    monkeypatch.setattr(get_settings(), "LIMIT_GUEST_RESUMES_PER_DAY", 1)
    r = await upload(client, h, make_pdf())
    assert r.status_code == 429 and r.headers["Retry-After"] and r.json()["error"]["code"] == "rate_limited"


async def test_upload_summarises_and_personalises_interview(client: AsyncClient, use_fake_llm) -> None:
    provider = use_fake_llm(jsons=[SUMMARY], tool_responses=["Tell me about your billing APIs?"], texts=["Title"])
    h = await guest(client)
    r = await upload(client, h, make_pdf())
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "cv.pdf" and body["pages"] == 1
    rid = body["resume_id"]

    status = (await client.get(f"{API}/resume/{rid}", headers=h)).json()
    assert status["ready"] is True and status["failed"] is False  # background task stored the summary

    r = await start(client, h, resume_id=rid)
    assert r.status_code == 200 and parse_sse(r.text)[-1][0] == "done"
    assert "billing APIs" in provider.calls[-1]["system"] or any("billing APIs" in c["system"] for c in provider.calls)


async def test_summary_failure_is_reported_not_raised(client: AsyncClient, use_fake_llm) -> None:
    use_fake_llm(jsons=[RuntimeError("provider down")])
    h = await guest(client)
    rid = (await upload(client, h, make_pdf())).json()["resume_id"]
    status = (await client.get(f"{API}/resume/{rid}", headers=h)).json()
    assert status["failed"] is True


async def test_resume_is_private_and_deletable(client: AsyncClient, use_fake_llm) -> None:
    use_fake_llm(jsons=[SUMMARY])
    a, b = await guest(client), await guest(client)
    rid = (await upload(client, a, make_pdf())).json()["resume_id"]
    assert (await client.get(f"{API}/resume/{rid}", headers=b)).status_code == 404
    assert (await client.delete(f"{API}/resume/{rid}", headers=b)).status_code == 404
    assert (await client.delete(f"{API}/resume/{rid}", headers=a)).status_code == 204
    assert (await client.get(f"{API}/resume/{rid}", headers=a)).status_code == 404
