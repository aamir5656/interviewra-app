"""Tests 16 and 17: lead-ins, "thanks", hints, tips, the injection note, the skill breakdown and leading follow-ups.
One block per bug."""
import copy

from httpx import AsyncClient

from app.services.evaluator import (
    CATEGORY_BAND, CRITICAL_CATEGORY_CAP, HINT_FALLBACK, INJECTION_MENTION, generate_report,
)
from app.services.question_text import split_question
from app.services.reply_checks import NEUTRAL_LEADS, check_reply, neutral_lead, sanitize
from tests.helpers import REPORT, guest, start_ok
from tests.test_agent import GOOD, _answer
from tests.test_answer_judge import _tokens

IDEMPOTENCY = ("I would send an idempotency key with every request and keep a unique constraint on it, so a retried request "
               "is ignored and the payment is created only once.")


# ---------- BUG 1: the lead-in must be about the candidate's last answer ----------


def test_bug1_a_lead_in_that_does_not_match_the_answer_is_replaced_by_a_neutral_line() -> None:
    raw = "Thanks for explaining how you handled messaging history. <q>What is a primary key?</q>"
    shown, q = split_question(sanitize(raw, "ok", new_topic=True, answer=IDEMPOTENCY, turn=2))
    assert shown == f"{neutral_lead(2)}\n\nWhat is a primary key?" and q == "What is a primary key?"
    kept, _ = split_question(sanitize("You mentioned the idempotency key. <q>What is a primary key?</q>", "ok", new_topic=True,
                                      answer=IDEMPOTENCY, turn=2))
    assert kept.startswith("You mentioned the idempotency key.")  # it shares a content word: kept
    plain, _ = split_question(sanitize("Understood. <q>What is a primary key?</q>", "ok", new_topic=True, answer=IDEMPOTENCY, turn=2))
    assert plain.startswith("Understood.")  # no content words: nothing to check


async def test_bug1_the_router_passes_the_answer_and_the_question_number(client: AsyncClient, use_fake_llm) -> None:
    use_fake_llm(tool_responses=["<q>What is an index?</q>", "Noted your view on kubernetes pods. <q>What is a primary key?</q>"], texts=["T"])
    h = await guest(client)
    sid = await start_ok(client, h)
    assert _tokens(await _answer(client, h, sid, GOOD)) == "Let us continue.\n\nWhat is a primary key?"  # question 2 -> third line


# ---------- BUG 2: no "thanks" at the start (except the closing message) ----------


def test_bug2_thanks_is_rejected_and_replaced_by_a_rotating_neutral_lead_in() -> None:
    assert check_reply("Thanks for explaining that. <q>What is an index?</q>", "ok", closing=False, must_ask=False, new_topic=True)
    assert check_reply("Thank you for that answer. What is an index?", "ok", closing=False, must_ask=False, new_topic=True)
    assert check_reply("Thank you for your time. The interview is complete.", "ok", closing=True, must_ask=False) == []
    out, _ = split_question(sanitize("Thanks for the detail. <q>What is an index?</q>", "ok", new_topic=True, answer=IDEMPOTENCY, turn=1))
    assert out.startswith(neutral_lead(1)) and "Thanks" not in out
    assert all(neutral_lead(n) != neutral_lead(n + 1) for n in range(1, 12)) and len(set(NEUTRAL_LEADS)) == len(NEUTRAL_LEADS)


def test_bug2_the_rule_is_in_the_prompts() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app" / "prompts"
    assert "Thanks" in (root / "interviewer.md").read_text() and "Thanks" in (root / "turn_notes.md").read_text()


# ---------- BUG 3: a hint never claims the candidate's approach still fails ----------


async def _report_with(use_fake_llm, answers: list[str], questions: list[str], transcript: str = "t", level: str = "junior",
                       role: str = "Backend Engineer", **fields) -> object:
    r = copy.deepcopy(REPORT)
    r["per_question"][0].update(fields)
    use_fake_llm(jsons=[r])
    return await generate_report(role, level, "technical", transcript, answers, questions, [False], None)


async def test_bug3_a_misleading_hint_is_replaced(use_fake_llm) -> None:
    wrong = "A race could still happen before the unique constraint is written."
    out = await _report_with(use_fake_llm, [IDEMPOTENCY], ["How do you stop duplicate payments?"], better_answer_hint=wrong, score=80)
    assert out.per_question[0].better_answer_hint == HINT_FALLBACK  # type: ignore[attr-defined]
    ok = await _report_with(use_fake_llm, [IDEMPOTENCY], ["How do you stop duplicate payments?"],
                            better_answer_hint="Mention how you would monitor failed retries in production.", score=80)
    assert ok.per_question[0].better_answer_hint == "Mention how you would monitor failed retries in production."  # type: ignore[attr-defined]


def test_bug3_the_rule_is_in_the_evaluator_prompt() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "app" / "prompts" / "evaluator.md").read_text()
    assert "never contradict" in text and "only state facts that are true" in text


# ---------- BUG 4: tips must fit this interview and this role ----------


async def test_bug4_unrelated_tips_are_dropped(use_fake_llm) -> None:
    r = copy.deepcopy(REPORT)
    r["improvement_tips"] = ["Study memory management and garbage collection for client-side state stores",
                             "Learn distributed lock mechanisms for background jobs",
                             "Review idempotency keys and unique constraints", "Practice answering directly"]
    use_fake_llm(jsons=[r])
    transcript = f"Interviewer: How do you stop duplicate payments?\nCandidate: {IDEMPOTENCY}"
    out = await generate_report("Backend Engineer", "junior", "technical", transcript, [IDEMPOTENCY], ["How do you stop duplicate payments?"],
                                [False], None, "idempotency payments")
    assert out.improvement_tips == ["Review idempotency keys and unique constraints", "Practice answering directly"]


async def test_bug4_software_jargon_is_dropped_for_a_data_analyst_and_one_tip_always_stays(use_fake_llm) -> None:
    r = copy.deepcopy(REPORT)
    r["improvement_tips"] = ["Learn software estimation and team velocity", "Study sprint burndown charts"]
    use_fake_llm(jsons=[r])
    transcript = "Interviewer: How do you handle missing values?\nCandidate: I check why values are missing and then impute."
    out = await generate_report("Data Analyst", "junior", "technical", transcript, ["I check why values are missing."],
                                ["How do you handle missing values?"], [False], None, "missing values imputation")
    assert len(out.improvement_tips) == 1  # never empty


# ---------- BUG 5: the injection is never listed under "To improve" ----------


def test_bug5_the_exact_sentence_is_recognised() -> None:
    sentence = "Sent one message that tried to instruct the interviewer instead of answering; it was ignored and not scored."
    assert INJECTION_MENTION.search(sentence)


async def test_bug5_it_is_removed_from_weaknesses_and_noted_once_in_the_feedback(use_fake_llm) -> None:
    r = copy.deepcopy(REPORT)
    r["weaknesses"] = ["Sent one message that tried to instruct the interviewer instead of answering; it was ignored and not scored.",
                       "Skipped edge cases"]
    use_fake_llm(jsons=[r])
    out = await generate_report("Backend Engineer", "junior", "technical", "t", [IDEMPOTENCY], ["What is an index?"], [False], 0)
    assert out.weaknesses == ["Skipped edge cases"]
    assert out.per_question[0].feedback.count("instruction to the interviewer") == 1


# ---------- BUG 6: the skill breakdown is not flat ----------


def _three_item_report(scores: list[int], critical_at: int | None = None) -> dict:
    r = copy.deepcopy(REPORT)
    template = r["per_question"][0]
    items = []
    for i, score in enumerate(scores):
        item = dict(template, question=f"Q{i + 1}?", score=score, feedback="Clear answer with a trade-off.")
        if i == critical_at:
            item.update(critical_mistake=True, mistakes=["Dangerous claim"], feedback="Wrong and dangerous claims.")
        items.append(item)
    r["per_question"] = items
    r["category_scores"] = {k: 50 for k in r["category_scores"]}  # the flat "50, 50, 50" from Test 17
    return r


async def test_bug6_the_breakdown_is_not_flat_and_stays_near_the_average(use_fake_llm) -> None:
    use_fake_llm(jsons=[_three_item_report([82, 40, 75])])
    deep = IDEMPOTENCY + " The trade-off is extra storage, for example a key table that I clean every week."
    out = await generate_report("Backend Engineer", "junior", "technical", "t", [deep, "I am not sure about this one at all.", deep],
                                ["Q1?", "Q2?", "Q3?"], [False, True, False], None)
    cats = out.category_scores.model_dump()
    avg = sum(q.score for q in out.per_question) / 3
    assert len(set(cats.values())) > 1
    assert all(abs(v - avg) <= CATEGORY_BAND + 1 for v in cats.values())


async def test_bug6_a_critical_mistake_may_lower_accuracy_below_the_band(use_fake_llm) -> None:
    use_fake_llm(jsons=[_three_item_report([82, 20, 75], critical_at=1)])
    out = await generate_report("Backend Engineer", "junior", "technical", "t", [IDEMPOTENCY, "I always use MD5 for passwords here.", IDEMPOTENCY],
                                ["Q1?", "Q2?", "Q3?"], [False, False, False], None)
    assert out.category_scores.technical_accuracy <= CRITICAL_CATEGORY_CAP


# ---------- BUG 7: a follow-up never hints at the solution ----------


def test_bug7_leading_follow_ups_are_rejected() -> None:
    for bad in ("How might breaking the task into smaller parts help you handle the load?",
                "Wouldn't a queue help to smooth out the spikes here?",
                "Would adding an index improve the query that you described?"):
        assert check_reply(bad, "wrong", closing=False, must_ask=True), bad
    for good in ("Which part of your answer makes you sure that retries are safe?",
                 "Can you explain why a unique constraint alone is enough here?",
                 "What happens in your design when two requests arrive at the same time?"):
        assert check_reply(good, "wrong", closing=False, must_ask=True) == [], good
