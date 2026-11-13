"""Bugs from Tests 7, 8, 12 and 13: a wrong or unprofessional answer must get a REAL follow-up turn (its own turn,
the same question, no new main question), also when no regex can see the mistake; plus the other new code rules."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.answer_judge import parse_verdict
from app.services.evaluator import MANY_MISTAKES_CAP, apply_code_rules
from app.services.prompts import render
from app.services.reply_checks import check_reply, sanitize
from app.services.tools import MIXED_PATTERN, _pool
from app.schemas import CategoryScores, PerQuestion, Report
from tests.helpers import guest, start_ok
from tests.test_agent import GOOD, _answer, _at_last_question, _main_questions, _row

BOX_MODEL = ("The total width of an element is only its content width because padding and border never change the size, "
             "and box-sizing border-box is a bug that I never use, so I give every element a fixed width in pixels.")
FOLLOW_UP = "One part needs a closer look: how padding changes size. What happens to the total width when you add padding?"


@pytest.fixture
def judge_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ANSWER_JUDGE", True)


def _tokens(events) -> str:
    return "".join(d["text"] for e, d in events if e == "token")


def _json_calls(provider) -> list:
    return [c for c in provider.calls if c["method"] == "chat_json"]


@pytest.mark.parametrize("data,expected", [
    ({"verdict": "wrong", "area": "how padding changes size"}, ("wrong", "how padding changes size")),
    ({"verdict": "Unprofessional", "area": "feedback"}, ("unprofessional", "feedback")),
    ({"verdict": "correct", "area": "ignored"}, ("correct", "")),
    ({"verdict": "partly"}, ("partly", "")),
    ({"verdict": "banana"}, ("correct", "")), ("not a dict", ("correct", "")), ({}, ("correct", "")),
    ({"verdict": "wrong", "area": "x" * 500}, ("wrong", "x" * 80)),
])
def test_parse_verdict(data, expected) -> None:
    assert parse_verdict(data) == expected


async def test_wrong_answer_no_regex_can_see_gets_a_follow_up_turn(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    # Test 12: CSS box-model answer with five wrong claims; Alex wrote one sentence and started the NEXT main question.
    provider = use_fake_llm(
        tool_responses=["How do padding, border and margin affect an element's total width?", FOLLOW_UP], texts=["T"],
        jsons=[{"verdict": "wrong", "area": "how padding changes size"}])
    h = await guest(client)
    sid = await start_ok(client, h)
    events = await _answer(client, h, sid, BOX_MODEL)
    assert _tokens(events) == FOLLOW_UP and events[-1][1]["ready_to_end"] is False
    assert (await _row(db, sid)).current_question_index == 1 and await _main_questions(db, sid) == 1  # no new main question
    turn = [c for c in provider.calls if c["method"] == "chat_with_tools"][-1]
    assert "get_next_topic" not in [t.name for t in turn["tools"]]
    assert "classified the candidate's last answer as: wrong" in turn["system"] and "how padding changes size" in turn["system"]
    assert len(_json_calls(provider)) == 1


async def test_correct_answer_moves_on_and_the_judge_is_used_once(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    provider = use_fake_llm(tool_responses=["Q1?", "Let us move on.\n\nWhat is an index?"], texts=["T"], jsons=[{"verdict": "correct", "area": ""}])
    h = await guest(client)
    sid = await start_ok(client, h)
    await _answer(client, h, sid, GOOD)
    assert (await _row(db, sid)).current_question_index == 2 and len(_json_calls(provider)) == 1


async def test_a_failing_judge_never_blocks_the_interview(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    use_fake_llm(tool_responses=["Q1?", "Let us move on.\n\nWhat is an index?"], texts=["T"], jsons=[RuntimeError("quota exhausted")])
    h = await guest(client)
    sid = await start_ok(client, h)
    events = await _answer(client, h, sid, GOOD)
    assert events[-1][0] == "done" and (await _row(db, sid)).current_question_index == 2


async def test_only_one_follow_up_then_the_interview_moves_on(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    # Test 7/8: the candidate repeats the same wrong claim after the follow-up: no second follow-up, no second judge call.
    provider = use_fake_llm(tool_responses=["Q1?", FOLLOW_UP, "Let us move on.\n\nWhat is an index?"], texts=["T"],
                            jsons=[{"verdict": "wrong", "area": "how padding changes size"}])
    h = await guest(client)
    sid = await start_ok(client, h)
    await _answer(client, h, sid, BOX_MODEL)
    await _answer(client, h, sid, BOX_MODEL + " I still think so.")
    assert (await _row(db, sid)).current_question_index == 2 and len(_json_calls(provider)) == 1


async def test_unprofessional_answer_to_a_technical_question_is_also_followed_up(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    # Test 13: "fill every empty cell with zero, change the chart until it looks right" got no follow-up.
    use_fake_llm(tool_responses=["Q1?", "One part needs a closer look: how you document changes. What would your team need to know?"],
                 texts=["T"], jsons=[{"verdict": "unprofessional", "area": "documenting changes to the data"}])
    h = await guest(client)
    sid = await start_ok(client, h)
    events = await _answer(client, h, sid, "I fill every empty cell with zero, I keep no backup and I adjust the numbers until the chart looks the way my manager expects it to look.")
    assert _tokens(events).endswith("know?") and (await _row(db, sid)).current_question_index == 1


async def test_judge_is_off_when_disabled(client: AsyncClient, db: AsyncSession, use_fake_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ANSWER_JUDGE", False)
    provider = use_fake_llm(tool_responses=["Q1?", "Let us move on.\n\nWhat is an index?"], texts=["T"])
    h = await guest(client)
    sid = await start_ok(client, h)
    await _answer(client, h, sid, BOX_MODEL)
    assert not _json_calls(provider) and (await _row(db, sid)).current_question_index == 2


async def test_wrong_final_answer_gets_a_follow_up_and_is_not_ended(client: AsyncClient, db: AsyncSession, use_fake_llm, judge_on) -> None:
    use_fake_llm(tool_responses=["Q1?", FOLLOW_UP, "Thank you."], texts=["T"], jsons=[{"verdict": "wrong", "area": "how padding changes size"}])
    h, sid = await _at_last_question(client, db)
    first = await _answer(client, h, sid, BOX_MODEL)
    assert first[-1][1]["ready_to_end"] is False and _tokens(first) == FOLLOW_UP
    second = await _answer(client, h, sid, "I would measure the box in the browser tools.")
    assert second[-1][1]["ready_to_end"] is True  # the code ends it after the follow-up answer


# ---------- a turn that moves on must not correct the previous answer ----------


def test_correction_then_new_question_is_rejected_and_cleaned() -> None:
    bad = "One part of that deserves a second look. Moving on: why do teams use branches?"
    assert check_reply(bad, "ok", closing=False, must_ask=False, new_topic=True)
    assert sanitize(bad, "ok", new_topic=True) == "Moving on: why do teams use branches?"
    fine = "Understood. Tell me about a time you made a mistake on a project?"
    assert check_reply(fine, "ok", closing=False, must_ask=False, new_topic=True) == []  # 'mistake' inside a question is fine


# ---------- Mixed interviews: introduction first, about half technical ----------


@pytest.mark.parametrize("count", [3, 5, 10])
def test_mixed_pattern_is_hr_first_and_mostly_technical(count: int) -> None:
    types = [MIXED_PATTERN[i % len(MIXED_PATTERN)] for i in range(count)]
    assert types[0] == "hr" and types.count("technical") >= count // 2
    assert all(not (a == b == "hr") for a, b in zip(types, types[1:]))


@pytest.mark.parametrize("role", ["Backend Engineer", "Data Analyst", "Product Manager", "QA Engineer", "DevOps Engineer"])
@pytest.mark.parametrize("itype", ["mixed", "hr"])
def test_hr_and_mixed_interviews_open_with_the_introduction(role: str, itype: str) -> None:
    assert _pool(role, "junior", itype, 0)[0]["topic"] == "Introduction"


# ---------- evaluator: several wrong claims, CV questions ----------


def _report(**item: object) -> Report:
    q = PerQuestion(question="Q?", answer_summary="s", score=int(item.pop("score", 60)), feedback="Some wrong claims.", **item)  # type: ignore[arg-type]
    return Report(overall_score=q.score, category_scores=CategoryScores(technical_accuracy=50, communication=50, depth=50, problem_solving=50),
                  summary="s", strengths=["a", "b"], weaknesses=["c", "d"], per_question=[q],
                  improvement_tips=["x", "y", "z"], recommended_topics=["a", "b", "c"])


def test_three_wrong_claims_cap_the_score_even_when_none_is_critical() -> None:
    mistakes = ["padding does not change size", "border-box is a bug", "margins never collapse"]
    out = apply_code_rules(_report(score=62, mistakes=mistakes), [BOX_MODEL])
    assert out.per_question[0].score == MANY_MISTAKES_CAP and not out.per_question[0].critical_mistake
    assert apply_code_rules(_report(score=62, mistakes=mistakes[:2]), [BOX_MODEL]).per_question[0].score == 62  # two wrong claims: no extra cap


def test_cv_question_hint_only_with_a_relevant_cv_and_a_non_hr_topic() -> None:
    base = dict(wrap_up=False, final_check=False, rolling_summary="", next_topic={"topic": "t", "difficulty": "easy", "type": "technical",
                "question_idea": "idea", "question_number": 2}, opening=False, question_count=5, answer_flag="ok", must_ask=False,
                qtype="technical", cv_mode="relevant", cv_field="", role_name="Backend Engineer", repeat=False, mistake_area="")
    assert "Build this question on a concrete item" in render("turn_notes", cv_hook=True, **base)
    assert "Build this question on a concrete item" not in render("turn_notes", cv_hook=False, **base)


# ---------- Test 14: closing never praises; a repeat keeps the scenario ----------


def test_closing_message_never_praises_or_grades() -> None:
    bad = "Thank you for your time, Daniyal. I appreciate your thoughtful answers throughout our discussion. Your report can now be generated."
    assert check_reply(bad, "ok", closing=True, must_ask=False)
    clean = sanitize(bad, "ok", closing=True)
    assert "appreciate" not in clean and "thoughtful" not in clean and "report can now be generated" in clean
    assert check_reply("Thank you for your time. The interview is complete and your report can now be generated.", "ok", closing=True, must_ask=False) == []
