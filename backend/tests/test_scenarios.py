"""Scenario matrix: whole interviews with the scripted provider; invariants must hold for every combination."""
import copy

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evaluator import check_report_invariants
from app.models import Message
from sqlalchemy import select
from tests.conftest import tool_response
from tests.helpers import API, REPORT, guest, start_ok
from tests.test_agent import END, NEXT, GOOD, _answer, _main_questions, _row
from tests.test_report_rules import LONG

STORY = LONG + " In my last project our team of four fixed the problem together and I led the work."


@pytest.mark.parametrize("itype", ["technical", "behavioral", "hr", "mixed"])
@pytest.mark.parametrize("n", [3, 5, 10])
async def test_full_interview_invariants(client: AsyncClient, db: AsyncSession, use_fake_llm, n: int, itype: str) -> None:
    report = copy.deepcopy(REPORT)
    report["per_question"] = [dict(REPORT["per_question"][0], question=f"Q{i}", score=70 + i % 5) for i in range(n)]
    use_fake_llm(
        tool_responses=["Question 1?"] + [x for k in range(2, n + 1) for x in (tool_response(NEXT), f"Question {k}?")]
        + [tool_response(END, text="Thank you, report coming.")],
        texts=["T"] * 3, jsons=[report],
    )
    h = await guest(client)
    sid = await start_ok(client, h, interview_type=itype, question_count=n, role_name="Data Analyst")
    flags = []
    for i in range(n):
        flags.append((await _answer(client, h, sid, STORY + f" ({i})"))[-1][1]["ready_to_end"])
    assert flags == [False] * (n - 1) + [True]  # the code ends exactly after the answer to the last question
    session = await _row(db, sid)
    assert session.current_question_index == n and await _main_questions(db, sid) == n
    topics = session.covered_topics
    assert len(topics) == n and len({t.lower() for t in topics}) == n  # no repeats
    assert (await client.post(f"{API}/interviews/{sid}/answer", json={"content": GOOD}, headers=h)).status_code == 409
    body = (await client.post(f"{API}/interviews/{sid}/end", headers=h)).json()
    assert len(body["per_question"]) == n
    from app.schemas import Report

    assert check_report_invariants(Report.model_validate(body), n) == []
    msgs = (await db.scalars(select(Message).where(Message.session_id == sid, Message.role == "assistant"))).all()
    assert all(m.content.count("?") <= 1 and len(m.content.split()) <= 120 for m in msgs)
