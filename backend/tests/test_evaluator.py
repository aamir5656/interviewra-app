import copy
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.models import Feedback, InterviewSession, Message
from app.services.evaluator import FALLBACK_SUMMARY, build_transcript, generate_report
from tests.helpers import API, REPORT, guest, start_ok

BAD_JSON = AppError("llm_bad_json", "bad", 502)


async def _finished_interview(client: AsyncClient, h: dict[str, str]) -> str:
    sid = await start_ok(client, h)
    await client.post(f"{API}/interviews/{sid}/answer", json={"content": "An index speeds up reads."}, headers=h)
    return sid


def _scaled(delta: int) -> dict:
    r = copy.deepcopy(REPORT)
    r["overall_score"] += delta
    r["category_scores"] = {k: v + delta for k, v in r["category_scores"].items()}
    r["per_question"][0]["score"] += delta
    r["strengths"] = ["Clear explanations", f"Extra strength {delta}"]
    r["summary"] = f"Summary {delta}"
    return r


async def test_end_returns_valid_report_and_saves(client: AsyncClient, db: AsyncSession, use_fake_llm) -> None:
    provider = use_fake_llm(tool_responses=["Q1?", "Q2?"], texts=["T"], jsons=[REPORT])
    h = await guest(client)
    sid = await _finished_interview(client, h)
    r = await client.post(f"{API}/interviews/{sid}/end", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["overall_score"] == 55 and body["is_fallback"] is False  # one short sentence is capped at 55
    assert "internal_analysis" not in body
    assert set(body) == {"overall_score", "category_scores", "summary", "strengths", "weaknesses", "per_question",
                         "improvement_tips", "recommended_topics", "is_fallback", "verdict", "has_critical"}
    assert body["recommended_topics"] == ["Indexing", "Transactions", "Caching"]

    session = await db.scalar(select(InterviewSession).where(InterviewSession.id == sid))
    assert session.status == "completed" and session.ended_at is not None
    fb = await db.scalar(select(Feedback).where(Feedback.session_id == session.id))
    assert fb.overall_score == 55 and fb.tips["recommended_topics"] == ["Indexing", "Transactions", "Caching"]
    system = provider.calls[-1]["system"]
    assert "Interviewer [main question 1 of 3]: Q1?" in system and "Candidate: An index speeds up reads." in system


async def test_end_is_idempotent_and_report_endpoint(client: AsyncClient, use_fake_llm) -> None:
    provider = use_fake_llm(tool_responses=["Q1?"], texts=["T"], jsons=[REPORT])  # only ONE evaluation is scripted
    h = await guest(client)
    sid = await start_ok(client, h)
    assert (await client.get(f"{API}/interviews/{sid}/report", headers=h)).status_code == 404
    first = await client.post(f"{API}/interviews/{sid}/end", headers=h)
    second = await client.post(f"{API}/interviews/{sid}/end", headers=h)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert sum(c["method"] == "chat_json" for c in provider.calls) == 1
    assert (await client.get(f"{API}/interviews/{sid}/report", headers=h)).json() == first.json()
    detail = (await client.get(f"{API}/interviews/{sid}", headers=h)).json()
    assert detail["status"] == "completed" and detail["feedback"] == first.json()


async def test_end_after_completion_blocks_more_answers(client: AsyncClient, use_fake_llm) -> None:
    use_fake_llm(tool_responses=["Q1?"], texts=["T"], jsons=[REPORT])
    h = await guest(client)
    sid = await start_ok(client, h)
    await client.post(f"{API}/interviews/{sid}/end", headers=h)
    r = await client.post(f"{API}/interviews/{sid}/answer", json={"content": "late"}, headers=h)
    assert r.status_code == 409


async def test_end_schedules_memory_update(client: AsyncClient, use_fake_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple] = []

    async def fake(user_id, session_id, factory=None) -> None:
        seen.append((user_id, session_id))

    monkeypatch.setattr("app.routers.interview.update_long_term_memory", fake)
    use_fake_llm(tool_responses=["Q1?"], texts=["T"], jsons=[REPORT])
    h = await guest(client)
    sid = await start_ok(client, h)
    await client.post(f"{API}/interviews/{sid}/end", headers=h)
    await client.post(f"{API}/interviews/{sid}/end", headers=h)  # idempotent call must not schedule again
    assert len(seen) == 1 and str(seen[0][1]) == sid
    

async def test_invalid_json_then_fixed_on_retry(use_fake_llm) -> None:
    bad_shape = {"overall_score": "n/a", "summary": "oops"}
    provider = use_fake_llm(jsons=[bad_shape, REPORT])
    report = await generate_report("Backend Engineer", "junior", "technical", "Interviewer: Q?\n\nCandidate: A")
    assert report.overall_score == 70 and not report.is_fallback
    retry = provider.calls[-1]["messages"]
    assert retry[-1].role == "user" and "valid JSON" in retry[-1].content and retry[-2].role == "assistant"


async def test_unparseable_reply_then_fixed_on_retry(use_fake_llm) -> None:
    provider = use_fake_llm(jsons=[BAD_JSON, REPORT])
    report = await generate_report("Backend Engineer", "junior", "technical", "Candidate: A")
    assert report.overall_score == 70 and len(provider.calls) == 2


async def test_total_failure_returns_fallback_and_is_saved(client: AsyncClient, use_fake_llm) -> None:
    provider = use_fake_llm(tool_responses=["Q1?"], texts=["T"], jsons=[BAD_JSON, {"nope": 1}])
    h = await guest(client)
    sid = await start_ok(client, h)
    r = await client.post(f"{API}/interviews/{sid}/end", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["is_fallback"] is True and body["summary"] == FALLBACK_SUMMARY and body["overall_score"] == 0
    assert sum(c["method"] == "chat_json" for c in provider.calls) == 2  # one try + one retry, no more
    assert (await client.get(f"{API}/interviews/{sid}/report", headers=h)).json()["is_fallback"] is True


async def test_provider_outage_is_an_error_not_a_fake_report(client: AsyncClient, db: AsyncSession, use_fake_llm) -> None:
    use_fake_llm(tool_responses=["Q1?"], texts=["T"], jsons=[AppError("llm_unavailable", "down", 503), REPORT])
    h = await guest(client)
    sid = await start_ok(client, h)
    r = await client.post(f"{API}/interviews/{sid}/end", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"
    session = await db.scalar(select(InterviewSession).where(InterviewSession.id == sid))
    assert session.status == "active" and await db.scalar(select(Feedback).where(Feedback.session_id == session.id)) is None
    assert (await client.post(f"{API}/interviews/{sid}/end", headers=h)).status_code == 200  # can be retried


async def test_scores_are_clamped_and_lists_cleaned(use_fake_llm) -> None:
    messy = copy.deepcopy(REPORT)
    messy.update(overall_score=140.6, strengths=["ok", "", "  "], recommended_topics=["a"] * 30)
    messy["category_scores"]["depth"] = -5
    messy["per_question"][0]["score"] = "250"
    use_fake_llm(jsons=[messy])
    r = await generate_report("Backend Engineer", "junior", "technical", "Candidate: A")
    assert r.overall_score == 100 and r.category_scores.depth == 85 and r.per_question[0].score == 100
    assert r.strengths == ["ok"] and len(r.recommended_topics) == 10


async def test_parallel_flag_merges_three_perspectives(use_fake_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ENABLE_PARALLEL_EVAL", True)
    provider = use_fake_llm(jsons=[_scaled(-10), _scaled(0), _scaled(10), {"summary": "One merged summary."}])
    body = (await generate_report("Backend Engineer", "junior", "technical", "T")).model_dump()
    assert body["overall_score"] == 70 and body["per_question"][0]["score"] == 70  # overall = average of the question scores
    assert body["category_scores"]["communication"] == 75
    assert body["summary"] == "One merged summary."
    assert body["strengths"] == ["Clear explanations", "Extra strength -10", "Extra strength 0", "Extra strength 10"]
    json_calls = [c for c in provider.calls if c["method"] == "chat_json"]
    assert len(json_calls) == 4
    focuses = [c["system"] for c in json_calls[:3]]
    assert all("Panel perspective" in s for s in focuses) and len({*focuses}) == 3
    assert "<analyses>" in json_calls[3]["system"]


async def test_parallel_survives_one_failed_perspective_and_falls_back_when_all_fail(
    use_fake_llm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ENABLE_PARALLEL_EVAL", True)
    # perspective 1 fails twice (bad JSON), perspectives 2 and 3 succeed, merge call fails -> first summary is kept
    use_fake_llm(jsons=[BAD_JSON, _scaled(0), _scaled(10), BAD_JSON, BAD_JSON, AppError("llm_bad_json", "x", 502)])
    report = await generate_report("Backend Engineer", "junior", "technical", "Candidate: A")
    assert not report.is_fallback and report.overall_score == 75
    use_fake_llm(jsons=[BAD_JSON] * 6)
    assert (await generate_report("Backend Engineer", "junior", "technical", "Candidate: A")).is_fallback


def test_transcript_labels_and_truncation() -> None:
    def m(role: str, text: str) -> Message:
        return Message(role=role, content=text)

    t = build_transcript([m("assistant", "Q1?"), m("tool", "ignored"), m("user", "A1"), m("user", "  ")])
    assert t == "Interviewer: Q1?\n\nCandidate: A1"
    long = build_transcript([m("user", "x" * 40_000)])
    assert long.startswith("[earlier part") and len(long) < 30_100


def _msg(role: str, text: str, *calls: str):
    from app.models import Message

    return Message(session_id=uuid.uuid4(), role=role, content=text, tool_calls=[{"name": c} for c in calls] or None)


def test_transcript_tags_follow_the_questions_the_interview_counted() -> None:
    from app.services.evaluator import build_transcript, count_main_questions

    rows = [
        _msg("assistant", "Q1?", "get_next_topic"), _msg("user", "a1"),
        _msg("assistant", "Can you add a detail?"), _msg("user", "a1b"),
        _msg("assistant", "Q2?", "get_next_topic"), _msg("user", "a2"),
        _msg("assistant", "Thanks, bye.", "end_interview"),
    ]
    text = build_transcript(rows, 2)
    assert "Interviewer [main question 1 of 2]: Q1?" in text
    assert "Interviewer [follow-up on main question 1]: Can you add a detail?" in text
    assert "Interviewer [main question 2 of 2]: Q2?" in text and "Interviewer [closing]: Thanks, bye." in text
    assert count_main_questions(rows) == 2
    assert "Interviewer: Q1?" in build_transcript(rows)  # without a total the old plain format is kept


def test_report_never_lists_more_questions_than_were_asked() -> None:
    from app.schemas import Report
    from app.services.evaluator import limit_questions

    extra = {**REPORT["per_question"][0], "question": "Invented", "score": 20}
    report = Report.model_validate({**REPORT, "per_question": [REPORT["per_question"][0], extra]})
    cut = limit_questions(report, 1)
    assert [q.question for q in cut.per_question] == ["What is an index?"] and cut.overall_score == 70
    assert limit_questions(report, 2) is report and limit_questions(report, 0) is report
