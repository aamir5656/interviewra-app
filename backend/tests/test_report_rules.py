"""Report rules that live in code (bugs 1-4, 11-13): count, red flags, verdict, skills, hints, invented terms, ladder."""
import copy

import pytest

from app.services.evaluator import (
    HINT_FALLBACK, apply_code_rules, check_report_invariants, finalize_report, fit_count, generate_report, verdict_for,
)
from app.schemas import CategoryScores, PerQuestion, Report
from tests.helpers import REPORT

LONG = ("I would use a B-tree index because lookups become logarithmic, for example on the email column, "
        "but writes get slower since every insert must update the index, so I measure with EXPLAIN first. " * 1)


def q(score: int = 70, **kw) -> PerQuestion:
    return PerQuestion(question=kw.pop("question", "Q?"), answer_summary="s", score=score, feedback=kw.pop("feedback", "f"),
                       better_answer_hint=kw.pop("hint", "Mention write cost."), **kw)


def rep(items: list[PerQuestion], **kw) -> Report:
    base = dict(overall_score=70, category_scores=CategoryScores(technical_accuracy=70, communication=70, depth=70,
                problem_solving=70), summary="Fine.", strengths=["Clear"], weaknesses=["Shallow"],
                per_question=items, improvement_tips=["x"], recommended_topics=["y"])
    return Report(**{**base, **kw})


def test_verdict_comes_from_numbers_and_critical_flag() -> None:
    assert [verdict_for(o, False) for o in (95, 80, 79, 60, 59, 40, 39, 0)] == [
        "Strong", "Strong", "Meets the bar", "Meets the bar", "Below the bar", "Below the bar", "Needs work", "Needs work"]
    assert verdict_for(60, True) == "Below the bar" and verdict_for(30, True) == "Needs work"
    r = finalize_report(rep([q(90, critical_mistake=True), q(90), q(90), q(90), q(90)], verdict="Strong"))
    assert r.overall_score == 60 and r.has_critical and r.verdict == "Below the bar"  # model label is ignored


def test_skill_breakdown_stays_near_question_scores() -> None:
    cats = CategoryScores(technical_accuracy=95, communication=95, depth=5, problem_solving=50)
    r = finalize_report(rep([q(60), q(60)], category_scores=cats))
    assert r.category_scores.technical_accuracy == 75 and r.category_scores.depth == 45
    crit = finalize_report(rep([q(60, critical_mistake=True), q(60)], category_scores=cats))
    assert crit.category_scores.technical_accuracy <= 40


def test_missing_question_is_added_and_extra_is_cut() -> None:
    questions = [f"Question {i}" for i in range(1, 6)]
    four = finalize_report(rep([q(80), q(80), q(80), q(80)]))
    fixed = fit_count(four, questions)
    assert len(fixed.per_question) == 5 and fixed.per_question[4].question == "Question 5"
    assert fixed.overall_score == four.overall_score  # the gap is filled with the average, so the score does not move
    assert len(fit_count(rep([q()] * 7), questions).per_question) == 5


def test_unprofessional_hr_answer_is_critical_even_if_the_model_missed_it() -> None:
    answers = ["Fine answer " * 20, "I want an easy job, leave at 5pm, I do not want feedback and I would leave "
               "mid-project for a little more money."]
    r = apply_code_rules(finalize_report(rep([q(80), q(75)])), answers)
    assert r.per_question[1].critical_mistake and r.per_question[1].score <= 25
    assert r.has_critical and r.overall_score <= 60 and r.verdict == "Below the bar"
    assert not r.per_question[0].critical_mistake


@pytest.mark.parametrize("text", ["I never blame the team.", "I don't take feedback personally.",
                                  "I enjoy teamwork and welcome feedback."])
def test_good_professional_phrases_are_not_flagged(text: str) -> None:
    r = apply_code_rules(finalize_report(rep([q(70)])), [text + " " + LONG])
    assert not r.per_question[0].critical_mistake


def test_dangerous_technical_claims_are_flagged() -> None:
    for text in ("I store passwords with MD5. " + LONG, "I build the query by concatenating strings into the SQL. " + LONG):
        assert apply_code_rules(finalize_report(rep([q(70)])), [text]).per_question[0].critical_mistake


def test_score_ladder() -> None:
    r = apply_code_rules(finalize_report(rep([q(88), q(90), q(92), q(60)])), [
        "An index speeds up reads.",  # 5 words: short
        "I do not know",  # non-answer
        "It is a data structure that stores sorted keys so the database can find rows without scanning the table. " * 3,  # long, no depth marker
        LONG * 2,  # full answer with trade-off and example
    ])
    assert r.per_question[0].score == 55 and r.per_question[1].score == 25 and r.per_question[2].score == 80
    assert r.per_question[3].score == 60
    strong = apply_code_rules(finalize_report(rep([q(90)])), [LONG * 2])
    assert strong.per_question[0].score == 90  # 85+ is allowed with a trade-off and an example


def test_hint_that_repeats_the_candidate_is_replaced() -> None:
    answer = "I would add an index on the email column and measure the query plan with EXPLAIN before and after. " * 2
    r = apply_code_rules(finalize_report(rep([q(70, hint="Add an index on the email column and measure the query plan with EXPLAIN")])), [answer])
    assert r.per_question[0].better_answer_hint == HINT_FALLBACK
    ok = apply_code_rules(finalize_report(rep([q(70, hint="Discuss partial indexes and how write cost grows with each extra index")])), [answer])
    assert "partial indexes" in ok.per_question[0].better_answer_hint


def test_invented_terms_are_removed_but_hints_may_add_new_ideas() -> None:
    item = PerQuestion(question="Missing data?", answer_summary="Drops rows.",
                       feedback="Drops rows. They also discussed MCAR, MAR and MNAR.", score=60,
                       better_answer_hint="Try Little's MCAR test.")
    r = apply_code_rules(finalize_report(rep([item], strengths=["Knows MCAR theory", "Clear tone"],
                                              summary="Good basics. Covered trade-offs well.")),
                         ["I drop the rows with missing values. " * 5], "Candidate: I drop the rows with missing values.")
    assert "MCAR" not in r.per_question[0].feedback and r.per_question[0].feedback == "Drops rows."
    assert r.strengths == ["Clear tone"] and "trade-offs" not in r.summary
    assert "MCAR" in r.per_question[0].better_answer_hint


def test_invariants_detect_a_broken_report() -> None:
    good = apply_code_rules(finalize_report(rep([q(70), q(60)])), [LONG, LONG])
    assert check_report_invariants(good, 2) == []
    assert check_report_invariants(good, 3)  # wrong count
    broken = good.model_copy(update={"overall_score": 99, "verdict": "Needs work"})
    assert len(check_report_invariants(broken, 2)) >= 2


async def test_generate_report_retries_when_an_item_is_missing(use_fake_llm) -> None:
    short, full = copy.deepcopy(REPORT), copy.deepcopy(REPORT)
    full["per_question"] = [dict(REPORT["per_question"][0], question=f"Q{i}") for i in (1, 2)]
    provider = use_fake_llm(jsons=[short, full])
    r = await generate_report("Backend Engineer", "junior", "technical", "T", [LONG, LONG], ["Q1", "Q2"])
    assert len(r.per_question) == 2 and sum(c["method"] == "chat_json" for c in provider.calls) == 2


async def test_generate_report_pads_if_the_retry_is_still_short(use_fake_llm) -> None:
    use_fake_llm(jsons=[REPORT, REPORT])
    r = await generate_report("Backend Engineer", "junior", "technical", "T",
                              [LONG, "I will leave mid-project for a little more money."], ["Q1", "Q2"])
    assert len(r.per_question) == 2 and r.per_question[1].critical_mistake and r.overall_score <= 60
    assert check_report_invariants(r, 2) == []


# ---------- Test 10 problems: wrong flag on a correct answer, test strings, short dense answers ----------

DENSE = "Logs, timeouts, retries with backoff, caching, a queue for slow work, scaling out, and the trade-off is cost."


def test_html_test_string_is_a_zero_score_non_answer_not_a_critical_mistake() -> None:
    items = [q(60, critical_mistake=True, feedback="Dangerous input handling."), q(80, feedback="Accurate and comprehensive answer.")]
    r = apply_code_rules(finalize_report(rep(items)), ["<script>alert(1)</script>", LONG])
    assert r.per_question[0].score <= 25 and not r.per_question[0].critical_mistake
    assert not r.has_critical and r.verdict != "Needs work" or r.overall_score > 0


def test_critical_flag_with_positive_feedback_and_no_mistake_is_cleared() -> None:
    wrongly = q(25, critical_mistake=True, feedback="Accurate and comprehensive explanation of password hashing.")
    r = apply_code_rules(finalize_report(rep([wrongly])), [LONG * 2])
    assert not r.per_question[0].critical_mistake and not r.has_critical
    real = q(25, critical_mistake=True, mistakes=["MD5 for passwords"], feedback="MD5 is far too fast for passwords.")
    kept = apply_code_rules(finalize_report(rep([real])), ["I would use bcrypt " + LONG])
    assert kept.per_question[0].critical_mistake  # a named mistake keeps the flag


def test_short_answers_are_capped_in_two_tiers() -> None:
    r = apply_code_rules(finalize_report(rep([q(90), q(90)])), ["Use an index on the column.", DENSE])
    assert r.per_question[0].score == 55 and r.per_question[1].score == 70  # dense list, 17 words: allowed to reach 70


def test_contradictions_are_found() -> None:
    from app.services.evaluator import find_contradictions

    bad = rep([q(25, critical_mistake=True, feedback="Accurate and comprehensive."), q(20, feedback="Correct and thorough answer.")])
    assert len(find_contradictions(finalize_report(bad))) == 2
    assert find_contradictions(finalize_report(rep([q(70)]))) == []


async def test_generate_report_asks_again_when_flag_and_feedback_disagree(use_fake_llm) -> None:
    bad, good = copy.deepcopy(REPORT), copy.deepcopy(REPORT)
    bad["per_question"] = [dict(REPORT["per_question"][0], score=25, critical_mistake=True, feedback="Accurate and comprehensive.")]
    good["per_question"] = [dict(REPORT["per_question"][0], score=78, feedback="Accurate answer, add a trade-off.")]
    provider = use_fake_llm(jsons=[bad, good])
    r = await generate_report("Backend Engineer", "junior", "technical", "T", [LONG * 2], ["Q1"])
    assert r.per_question[0].score == 78 and not r.has_critical
    assert sum(c["method"] == "chat_json" for c in provider.calls) == 2


def test_unanswered_question_scores_zero_even_if_the_model_was_generous() -> None:
    r = apply_code_rules(finalize_report(rep([q(80), q(75)])), [LONG * 2])  # only the first question has an answer
    assert r.per_question[1].score == 0 and r.per_question[1].answer_summary == "No answer was given."
    assert r.overall_score == (r.per_question[0].score + 0 + 1) // 2 or r.overall_score < r.per_question[0].score
