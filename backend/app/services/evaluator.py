import asyncio
import json
import logging
import re
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.core.errors import AppError
from app.models import Feedback, Message, MessageRole
from app.schemas import CategoryScores, PerQuestion, Report, clamp_score
from app.services.llm import get_provider
from app.services.llm.base import ChatMessage, LLMProvider
from app.services.prompts import render
from app.services.question_text import question_of

logger = logging.getLogger("app.evaluator")

MAX_TRANSCRIPT_CHARS = 30_000
EVALUATE_TEXT = "Evaluate this interview now and reply with the JSON object."
PERSPECTIVES: dict[str, str] = {
    "technical_accuracy": "technical accuracy: correctness of facts and solutions",
    "communication": "communication: clarity, structure and tone",
    "depth": "depth: reasoning, trade-offs and concrete examples",
}
MERGED_LIST_CAPS = {"strengths": 5, "weaknesses": 5, "improvement_tips": 5, "recommended_topics": 6}
FALLBACK_SUMMARY = (
    "We could not generate a detailed AI report for this interview. "
    "Your answers were saved; please try another interview to get full feedback."
)

# Scoring rules that are enforced here, in code, so they do not depend on the model following the prompt.
CRITICAL_SCORE_CAP = 25  # a question with a critical mistake (for example MD5 passwords, secrets in the frontend)
PROMPTED_SCORE_CAP = 75  # a question that only became correct after a follow-up or hint
CRITICAL_OVERALL_CAP = 60  # the overall score when any question has a critical mistake
CATEGORY_BAND = 15  # a skill score may differ from the average question score by at most this much
CRITICAL_CATEGORY_CAP = 40  # technical accuracy when any question has a critical mistake
VERY_SHORT_WORDS = 12  # fewer words than this cannot score above VERY_SHORT_CAP
VERY_SHORT_CAP = 55
SHORT_ANSWER_WORDS = 25  # a short but dense answer (a list of real points) can reach SHORT_ANSWER_CAP
SHORT_ANSWER_CAP = 70
NON_ANSWER_CAP = 25  # "I don't know" and similar
MANY_MISTAKES = 3  # an answer with this many named wrong claims cannot score above MANY_MISTAKES_CAP
MANY_MISTAKES_CAP = 30
STRONG_NEEDS_DEPTH_CAP = 80  # 85+ needs a trade-off or a concrete example, and a reasonably full answer
STRONG_MIN_WORDS = 60
VERDICT_BANDS = ((80, "Strong"), (60, "Meets the bar"), (40, "Below the bar"), (0, "Needs work"))
PROMPT_FLAGS = frozenset({"non_answer", "vague", "wrong"})  # the interviewer had to help: "I don't know", vague, wrong
IGNORED_FLAGS = frozenset({"instruction", "off_topic"})  # not an answer attempt: neither prompting nor a score reason
INJECTION_MENTION = re.compile(
    r"inject|ignore (all |any |your |the )*(previous |prior )*instructions|system prompt|override|jailbreak|prompt[- ]?hijack|"
    r"instruct(ed|ing)? the interviewer|manipulat|bypass|\b100\s*/\s*100\b|skip the remaining|end the interview", re.I)
INJECTION_LINE = "Sent one message that tried to instruct the interviewer instead of answering; it was ignored and not scored."
ADVANCED_FOR_JUNIOR = re.compile(
    r"\b(MCAR|MNAR|MAR|Little'?s|circuit[- ]breakers?|CAP theorem|eventual consistency|idempotenc\w+|bulkhead|back-?pressure|"
    r"consensus|paxos|raft|vector clocks?|MVCC|git bisect|reflog|document outline|decompil\w+|work factor|cost factor)\b", re.I)
HINT_ASSERTS_FAILURE = re.compile(
    r"\b(could|can|might|may) still (happen|fail|occur|break|be a problem)\b|\b(is|are|was) not enough\b|\bisn'?t enough\b|"
    r"\bwould not (work|prevent|help)\b|\b(does not|doesn'?t) prevent\b|\bbefore the [^.]{0,40}\b(is|are) (written|committed|saved)\b", re.I)
GENERIC_TIP_WORDS = frozenset((
    "practice practise answer answers question questions example examples explain explaining structure structured method methods "
    "clear clearly concise directly communicate communication interview interviews prompt prompts without needing before about study "
    "review reviews learn learning basics basic fundamentals concepts concept topics topic technical behavioral professional "
    "thoroughly confidence effectively general understand understanding improve improving skills skill approach approaches details "
    "detail specific trade tradeoff tradeoffs using response responses first attempt attempts hints hint feedback teamwork "
    "collaboration team stakeholders needed need keep give giving ensure focus common best practices real world project projects "
    "simple small different using write writing speak speaking think thinking steps step list lists point points").split())
INJECTION_NOTE = "One message in this question was an instruction to the interviewer, not an answer; it was ignored and not scored."
HINT_FALLBACK = "Add one concrete example or trade-off from your own experience to go beyond what you already said."
STOPWORDS = frozenset(
    "that this with from have they them then than will would could should what when where which while about into "
    "also your their there been were more some such only very over each other like just make made using used use".split()
)

# Phrases that are red flags in an HR / behavioral answer (and a few dangerous technical claims). They are a safety
# net in code: if the model forgets to flag the question, the flag is set here.
RED_FLAG_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\b(leave|quit|abandon|walk away from)\b[^.!?]{0,40}\b(mid[- ]?project|middle of (a|the|my) project|halfway)",
    r"\b(don'?t|do not)\b[^.!?]{0,12}\b(want|need|accept)\b[^.!?]{0,15}\bfeedback\b",
    r"(?<!never )(?<!not )\b(avoid|hate|dislike|don'?t like|do not like|refuse)\b[^.!?]{0,20}\b(team ?work|working (in|with) (a )?teams?|colleagues|collaborat)",
    r"\b(leave|go home|clock out)\b[^.!?]{0,15}\bat 5\b",
    r"(?<!never )(?<!not )(?<!n't )\bblame[sd]?\b[^.!?]{0,25}\b(team|colleague|manager|boss|others?)\b",
    r"\bmd5\b[^.!?]{0,40}\bpassword|\bpasswords?\b[^.!?]{0,40}\bmd5\b",
    r"\bpasswords?\b[^.!?]{0,30}\b(plain ?text|unencrypted)\b",
    r"\b(concatenat\w+)\b[^.!?]{0,40}\b(sql|query|queries)\b",
))
INSTRUCTION = re.compile(
    r"ignore (all |your |the |any )*(previous |above |prior )*(instructions|rules|prompt)|system prompt|"
    r"\b(give|rate|score) (me|this)\b[^.!?]{0,20}\b(100|10/10|full marks|top score)|\b100\s*/\s*100\b|you are now\b|"
    r"\bpretend (you|to be|that)\b|\b(end|stop|finish) (the|this) interview\b|call (the )?(end_interview|get_user_memory|get_next_topic)|"
    r"reveal (your|the) (prompt|instructions)", re.I)
POSITIVE_FEEDBACK = re.compile(
    r"\b(accurate|comprehensive|correct|excellent|thorough|well[- ]structured|solid|strong answer|clear and)\b", re.I)
NEGATIVE_FEEDBACK = re.compile(
    r"\b(mistake|incorrect|wrong|insecure|dangerous|serious|unsafe|critical|vulnerab\w*|plain ?text|md5|harm\w*|"
    r"not (safe|secure|correct|accurate)|inaccurate|misunderstand\w*)\b", re.I)
HTML_TAG = re.compile(r"<[^>]{0,200}>")
NON_ANSWER = re.compile(r"^\W*(i\s*(do not|don'?t|dont)\s*know|idk|no idea|not sure|skip|pass|nothing)\W*$", re.I)
DEPTH_MARKERS = re.compile(
    r"trade[- ]?off|however|downside|drawback|because|for example|for instance|e\.g\.|in my (last|previous|current)|"
    r"i (built|used|worked|fixed|solved|implemented|led|measured)|\d", re.I)


class ReportParseError(Exception):
    """The model answered, but twice without a usable report."""


def _has_call(calls: object, name: str) -> bool:
    return any(isinstance(c, dict) and c.get("name") == name for c in (calls or []))  # type: ignore[union-attr]


def build_transcript(messages: Sequence[Message], total_questions: int | None = None) -> str:
    """'Interviewer:' / 'Candidate:' lines in order; the oldest part is dropped if the text is very long.

    With `total_questions`, interviewer lines are tagged from the same record the interview used to count questions
    ("[main question 2 of 5]", "[follow-up on main question 2]", "[closing]"), so the report and the interview agree.
    """
    labels = {MessageRole.assistant.value: "Interviewer", MessageRole.user.value: "Candidate"}
    lines: list[str] = []
    asked = 0
    for m in messages:
        if m.role not in labels or not m.content.strip():
            continue
        label = labels[m.role]
        flagged = [str((c.get("arguments") or {}).get("flag", "")) for c in (m.tool_calls or [])
                   if isinstance(c, dict) and c.get("name") == "answer_flag"]
        ignored = m.role == MessageRole.assistant.value and any(f in IGNORED_FLAGS for f in flagged)
        if ignored and lines and lines[-1].startswith("Candidate:"):  # the message before was not an answer attempt
            lines[-1] = lines[-1].replace("Candidate:", "Candidate [not an answer: ignored, does not count]:", 1)
        if total_questions is not None and m.role == MessageRole.assistant.value:
            if ignored and not _has_call(m.tool_calls, "get_next_topic"):
                label = f"Interviewer [asks main question {asked} again; this is not a hint]"
            elif _has_call(m.tool_calls, "get_next_topic"):
                asked += 1
                label = f"Interviewer [main question {asked} of {total_questions}]"
            elif _has_call(m.tool_calls, "end_interview"):
                label = "Interviewer [closing]"
            elif asked:
                label = f"Interviewer [follow-up on main question {asked}]"
        lines.append(f"{label}: {m.content.strip()}")
    text = "\n\n".join(lines)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = "[earlier part of the transcript omitted]\n" + text[-MAX_TRANSCRIPT_CHARS:]
    return text


def count_main_questions(messages: Sequence[Message]) -> int:
    """How many main questions were really asked: interviewer messages whose turn counted a get_next_topic call."""
    return sum(1 for m in messages if m.role == MessageRole.assistant.value and _has_call(m.tool_calls, "get_next_topic"))


def limit_questions(report: Report, asked: int) -> Report:
    """Safety net: the report never lists more questions than were asked (the overall score is recalculated)."""
    if asked <= 0 or len(report.per_question) <= asked:
        return report
    return finalize_report(report.model_copy(update={"per_question": report.per_question[:asked]}))


def main_questions(messages: Sequence[Message]) -> list[str]:
    """Text of every real main question, in order (an interviewer message whose turn counted a get_next_topic call)."""
    return [question_of(m.content, m.tool_calls) for m in messages
            if m.role == MessageRole.assistant.value and _has_call(m.tool_calls, "get_next_topic")]


def answer_flags(messages: Sequence[Message]) -> list[list[str]]:
    """Per main question, the flags recorded for the candidate's answers (an answer is flagged by the interviewer reply
    that follows it, so the flag belongs to the question asked BEFORE that reply)."""
    out: list[list[str]] = []
    for m in messages:
        if m.role != MessageRole.assistant.value:
            continue
        for c in m.tool_calls or []:
            if isinstance(c, dict) and c.get("name") == "answer_flag" and out:
                out[-1].append(str((c.get("arguments") or {}).get("flag", "")))
        if _has_call(m.tool_calls, "get_next_topic"):
            out.append([])
    return out


def prompted_by_question(messages: Sequence[Message]) -> list[bool]:
    """True when the candidate needed help on that question; an instruction or off-topic message is not help."""
    return [any(f in PROMPT_FLAGS for f in flags) for flags in answer_flags(messages)]


def injection_question(messages: Sequence[Message]) -> int | None:
    """Index of the first main question on which the candidate sent an instruction instead of an answer."""
    return next((i for i, flags in enumerate(answer_flags(messages)) if "instruction" in flags), None)


def answers_by_question(messages: Sequence[Message]) -> list[str]:
    """All candidate text that belongs to each main question (answers, retries and follow-up answers), in order."""
    out: list[list[str]] = []
    for m in messages:
        if m.role == MessageRole.assistant.value and _has_call(m.tool_calls, "get_next_topic"):
            out.append([])
        elif m.role == MessageRole.user.value and out and m.content.strip():
            out[-1].append(m.content.strip())
    return [" ".join(parts) for parts in out]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def fit_count(report: Report, questions: Sequence[str]) -> Report:
    """Exactly one per_question item per main question: extra items are cut, missing ones are added.

    A missing item gets the average score of the other items (so the overall score does not move) and a plain note;
    the code rules below can still flag it from the candidate's answer.
    """
    n = len(questions)
    items = list(report.per_question)
    if n <= 0 or len(items) == n:
        return report
    items = items[:n]
    fill = _mean([q.score for q in items]) if items else 0
    for text in questions[len(items):]:
        items.append(PerQuestion(question=text[:300], answer_summary="", score=fill,
                                 feedback="No detailed feedback was produced for this question."))
    return finalize_report(report.model_copy(update={"per_question": items}))


def _drop_sentences(text: str, bad: "re.Pattern[str] | None", keep_if: "re.Pattern[str] | None" = None) -> str:
    if bad is None:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [x for x in parts if not (bad.search(x) and not (keep_if and keep_if.search(x)))]
    return " ".join(kept)


_ACRONYM = re.compile(r"\b[A-Z]{3,}s?\b")
_POSITIVE_TRADEOFF = re.compile(r"trade[- ]?offs?", re.I)
_NEGATED = re.compile(r"\b(not|no|never|without|lack\w*|miss\w*|didn'?t|did not|omit\w*|absent)\b", re.I)
_TRADEOFF_WORDS = re.compile(r"trade[- ]?off|downside|drawback|\bversus\b|\bvs\b|pros and cons|on the other hand", re.I)


def _unseen_acronyms(text: str, evidence: str) -> set[str]:
    return {a for a in _ACRONYM.findall(text) if a.lower().rstrip("s") not in evidence}


def _contradicts_critical(q: PerQuestion) -> bool:
    """A critical flag whose own feedback is positive and names no problem, or that lists no mistake at all."""
    positive = bool(POSITIVE_FEEDBACK.search(q.feedback)) and not NEGATIVE_FEEDBACK.search(q.feedback)
    return positive or not q.mistakes and not NEGATIVE_FEEDBACK.search(q.feedback)


def find_contradictions(report: Report) -> list[str]:
    """Items whose flag and feedback disagree; the evaluator is asked once to fix them."""
    out: list[str] = []
    for i, q in enumerate(report.per_question, 1):
        if q.critical_mistake and _contradicts_critical(q):
            out.append(f"item {i} is marked critical_mistake, but its feedback does not name any mistake "
                       "(list the mistakes in \"mistakes\" or set critical_mistake to false)")
        elif not q.critical_mistake and q.score <= CRITICAL_SCORE_CAP and POSITIVE_FEEDBACK.search(q.feedback) \
                and not NEGATIVE_FEEDBACK.search(q.feedback):
            out.append(f"item {i} has a score of {q.score} but its feedback is positive; make them agree")
    return out


def apply_code_rules(
    report: Report, answers: Sequence[str], transcript: str = "", prompted: Sequence[bool] | None = None,
    level: str = "", injection_at: int | None = None, topic_text: str = "",
) -> Report:
    """Rules about the report that must not depend on the model. `answers[i]` is the candidate text for question i.

    1. A red-flag phrase in the answer (unprofessional HR/behavioral answer, MD5 passwords, ...) sets critical_mistake.
    2. A non-answer ("I don't know") scores at most NON_ANSWER_CAP; a very short answer at most SHORT_ANSWER_CAP.
    3. A score of 85+ needs a reasonably full answer that contains a trade-off, reason or concrete example.
    4. A better_answer_hint that only repeats the candidate's own words is replaced.
    5. Feedback sentences with an acronym that appears nowhere in the transcript are dropped (no invented details), and
       strengths/summary may not praise "trade-offs" when the candidate never discussed any.
    Finally the caps, the overall score, the verdict and the skill breakdown are recomputed (finalize_report).
    """
    evidence = transcript.lower() + " " + " ".join(answers).lower()
    all_answers = " ".join(answers)
    items: list[PerQuestion] = []
    for i, q in enumerate(report.per_question):
        text = answers[i] if i < len(answers) else ""
        n_words = len(text.split())
        update: dict[str, Any] = {}
        score, critical = q.score, q.critical_mistake
        plain = HTML_TAG.sub(" ", text).strip()  # an HTML test string is not an answer
        no_content = bool(text) and (len(plain.split()) < 3 or bool(NON_ANSWER.match(plain)))
        red_flag = bool(text) and any(p.search(text) for p in RED_FLAG_PATTERNS)
        if not text:  # the question was asked but never answered (the candidate pressed End): nothing to credit
            update["answer_summary"] = "No answer was given."
            score, critical = 0, False
        if prompted is not None and i < len(prompted):  # decided from the recorded answer flags, not by the model
            update["needed_prompting"] = prompted[i]
        hint = q.better_answer_hint or ""
        if (level in ("intern", "junior") and ADVANCED_FOR_JUNIOR.search(hint)) or HINT_ASSERTS_FAILURE.search(hint):
            update["better_answer_hint"] = HINT_FALLBACK  # too advanced, or it claims the candidate's approach still fails
        if red_flag:
            critical = True
        if no_content or (text and INSTRUCTION.search(text) and n_words < STRONG_MIN_WORDS):
            score = min(score, NON_ANSWER_CAP)  # a non-answer, a test string or an injection: zero-ish, never "critical"
            critical = critical and red_flag
        elif critical and not red_flag and _contradicts_critical(q):
            critical = False  # the model flagged it, but its own feedback calls the answer fine
        elif text and n_words < VERY_SHORT_WORDS and not critical:
            score = min(score, VERY_SHORT_CAP)
        elif text and n_words < SHORT_ANSWER_WORDS and not critical:
            score = min(score, SHORT_ANSWER_CAP)
        if len(q.mistakes) >= MANY_MISTAKES and not no_content:
            score = min(score, MANY_MISTAKES_CAP)  # several wrong claims: a weak answer, flagged or not
        if score >= 85 and text and (n_words < STRONG_MIN_WORDS or not DEPTH_MARKERS.search(text)):
            score = min(score, STRONG_NEEDS_DEPTH_CAP)
        hint_words = {w for w in _words(q.better_answer_hint) if len(w) >= 4 and w not in STOPWORDS}
        if text and len(hint_words) >= 4:
            if len(hint_words & set(_words(text))) / len(hint_words) >= 0.7:
                update["better_answer_hint"] = HINT_FALLBACK
        for field in ("answer_summary", "feedback"):
            old = getattr(q, field)
            bad = {a for a in _unseen_acronyms(old, evidence)}
            if bad:
                update[field] = _drop_sentences(old, re.compile("|".join(map(re.escape, bad))))
        items.append(q.model_copy(update={**update, "score": score, "critical_mistake": critical}))

    def unseen(text: str) -> str:
        bad = _unseen_acronyms(text, evidence)
        return _drop_sentences(text, re.compile("|".join(map(re.escape, bad))) if bad else None)

    def clean(text: str) -> str:
        out = unseen(text)
        if all_answers and not _TRADEOFF_WORDS.search(all_answers):
            out = _drop_sentences(out, _POSITIVE_TRADEOFF, keep_if=_NEGATED)
        return out

    update_all = {
        "per_question": items,
        "summary": clean(report.summary) or report.summary,
        "strengths": [x for x in (clean(t) for t in report.strengths) if x],
        "weaknesses": [x for x in (unseen(t) for t in report.weaknesses) if x],
    }
    final = derive_skills(finalize_report(report.model_copy(update=update_all)), answers, prompted)
    final = drop_irrelevant_tips(final, f"{transcript} {topic_text}")
    return normalize_injection(final, injection_at)


def derive_skills(report: Report, answers: Sequence[str], prompted: Sequence[bool] | None) -> Report:
    """The skill breakdown comes from evidence in the interview, within CATEGORY_BAND of the average question score.

    accuracy follows the scores (and is capped after a critical mistake); depth follows how many answers gave a
    trade-off or a concrete example; communication drops with every answer that needed help or was a non-answer; problem
    solving follows the share of questions solved on the first try. A model's flat "50, 50, 50" can no longer reach a report.
    """
    items = report.per_question
    if not items:
        return report
    n = len(items)
    scores = [q.score for q in items]
    avg = sum(scores) / n
    texts = [*answers, *([""] * n)][:n]
    deep = sum(1 for t in texts if len(t.split()) >= STRONG_MIN_WORDS // 2 and DEPTH_MARKERS.search(t))
    helped = [(prompted[i] if prompted is not None and i < len(prompted) else items[i].needed_prompting)
              or items[i].score <= NON_ANSWER_CAP for i in range(n)]
    solid = sum(1 for i in range(n) if scores[i] >= 70 and not helped[i])
    raw = {
        "technical_accuracy": avg,
        "depth": avg + round(30 * (deep / n - 0.5)),
        "communication": avg + round(10 - 25 * (sum(helped) / n)),
        "problem_solving": avg + round(20 * (solid / n - 0.5)),
    }
    lo, hi = max(0, round(avg) - CATEGORY_BAND), min(100, round(avg) + CATEGORY_BAND)
    values = {k: min(max(round(v), lo), hi) for k, v in raw.items()}
    if report.has_critical:
        values["technical_accuracy"] = min(values["technical_accuracy"], CRITICAL_CATEGORY_CAP)  # a rule may lower it
    return report.model_copy(update={"category_scores": CategoryScores(**values)})


GENERIC_TIP_STEMS = frozenset(w[:6] for w in GENERIC_TIP_WORDS)  # "answer" also covers "answering", "direct" covers "directly"


def _tip_words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{5,}", text.lower()) if w[:6] not in GENERIC_TIP_STEMS}


def drop_irrelevant_tips(report: Report, vocabulary: str) -> Report:
    """Drop a tip about something that was neither said in this interview nor part of the asked topics.

    A tip is kept when it has no specific words at all (generic advice) or when at least half of its specific words occur in
    the transcript or in the asked topics; at least one tip always stays.
    """
    if not vocabulary.strip() or not report.improvement_tips:
        return report
    known = _tip_words(vocabulary)

    def relevant(tip: str) -> bool:
        words = _tip_words(tip)
        return not words or len(words & known) * 2 >= len(words)

    kept = [t for t in report.improvement_tips if relevant(t)]
    return report.model_copy(update={"improvement_tips": kept or report.improvement_tips[:1]})


def normalize_injection(report: Report, injection_at: int | None) -> Report:
    """A message that tried to instruct the interviewer is mentioned once, neutrally, in THAT question's feedback only.

    Every other mention (other questions, summary, strengths, weaknesses, tips) is removed, so the candidate is not
    punished twice and "To improve" never lists it.
    """
    def scrub(text: str, fallback: str) -> str:
        out = _drop_sentences(text, INJECTION_MENTION)
        return out if out.strip() else (fallback if INJECTION_MENTION.search(text) else text)

    items = []
    for i, q in enumerate(report.per_question):
        feedback = scrub(q.feedback, "Scored on the answer that was actually given.")
        if injection_at == i:
            feedback = f"{feedback} {INJECTION_NOTE}".strip()
        items.append(q.model_copy(update={
            "answer_summary": scrub(q.answer_summary, "Gave an answer to the question."),
            "feedback": feedback,
            "better_answer_hint": scrub(q.better_answer_hint, HINT_FALLBACK),
        }))
    return report.model_copy(update={
        "per_question": items,
        "summary": scrub(report.summary, "See the question-by-question feedback below.") or report.summary,
        "strengths": [x for x in report.strengths if not INJECTION_MENTION.search(x)],
        "weaknesses": [x for x in report.weaknesses if not INJECTION_MENTION.search(x)],
        "improvement_tips": [x for x in report.improvement_tips if not INJECTION_MENTION.search(x)],
    })


def check_report_invariants(report: Report, asked: int | None = None) -> list[str]:
    """Problems that must never be present in a stored report (used in tests and logged at runtime)."""
    problems: list[str] = []
    if report.is_fallback:
        return problems
    items = report.per_question
    if asked is not None and len(items) != asked:
        problems.append(f"{len(items)} report items for {asked} main questions")
    for i, q in enumerate(items):
        if not 0 <= q.score <= 100:
            problems.append(f"item {i + 1}: score out of range")
        if not q.feedback.strip():
            problems.append(f"item {i + 1}: no feedback")
        if q.critical_mistake and q.score > CRITICAL_SCORE_CAP:
            problems.append(f"item {i + 1}: critical but score {q.score}")
    if items:
        avg = _mean([q.score for q in items])
        if report.overall_score != (min(avg, CRITICAL_OVERALL_CAP) if any(q.critical_mistake for q in items) else avg):
            problems.append("overall score is not the average of the items")
        if any(q.critical_mistake for q in items) and report.overall_score > CRITICAL_OVERALL_CAP:
            problems.append("critical mistake but overall above cap")
        if report.verdict != verdict_for(report.overall_score, report.has_critical):
            problems.append("verdict does not match the numbers")
    return problems


def fallback_report() -> Report:
    zero = CategoryScores(technical_accuracy=0, communication=0, depth=0, problem_solving=0)
    return Report(
        overall_score=0, category_scores=zero, summary=FALLBACK_SUMMARY, strengths=[], weaknesses=[],
        per_question=[], improvement_tips=[], recommended_topics=[], is_fallback=True,
    )


def _parse(data: dict[str, Any]) -> Report:
    data = dict(data)
    data.pop("internal_analysis", None)
    return Report.model_validate(data)


def _mean(values: Sequence[int]) -> int:
    return clamp_score(sum(values) / len(values))


def verdict_for(overall: int, critical: bool) -> str:
    """One word for the overall score. A critical mistake can never read 'Meets the bar' or better."""
    label = next(name for floor, name in VERDICT_BANDS if overall >= floor)
    return "Below the bar" if critical and label in ("Strong", "Meets the bar") else label


def _derive_categories(cats: CategoryScores, scores: Sequence[int], critical: bool) -> CategoryScores:
    """Keep each skill within CATEGORY_BAND of the average question score (the model's numbers can disagree)."""
    avg = sum(scores) / len(scores)
    lo, hi = max(0, round(avg) - CATEGORY_BAND), min(100, round(avg) + CATEGORY_BAND)
    values = {f: min(max(getattr(cats, f), lo), hi) for f in CategoryScores.model_fields}
    if critical:
        values["technical_accuracy"] = min(values["technical_accuracy"], CRITICAL_CATEGORY_CAP)
    return CategoryScores(**values)


def finalize_report(report: Report) -> Report:
    """Apply the scoring rules the model must not decide alone.

    - a question with a critical mistake scores at most CRITICAL_SCORE_CAP;
    - a question that needed a follow-up or hint to become correct scores at most PROMPTED_SCORE_CAP;
    - overall_score is the average of the per-question scores (the model's own overall number is ignored), and it is at
      most CRITICAL_OVERALL_CAP when any question has a critical mistake.
    - the verdict label and the skill breakdown are derived from those numbers (see verdict_for, _derive_categories).
    A report without per-question items keeps the overall score it came with.
    """
    questions: list[PerQuestion] = []
    for q in report.per_question:
        cap = CRITICAL_SCORE_CAP if q.critical_mistake else PROMPTED_SCORE_CAP if q.needed_prompting else 100
        questions.append(q.model_copy(update={"score": min(q.score, cap)}) if q.score > cap else q)
    if not questions:
        return report.model_copy(update={"verdict": verdict_for(report.overall_score, False), "has_critical": False})
    critical = any(q.critical_mistake for q in questions)
    overall = _mean([q.score for q in questions])
    if critical:
        overall = min(overall, CRITICAL_OVERALL_CAP)
    return report.model_copy(update={
        "per_question": questions, "overall_score": overall, "has_critical": critical,
        "verdict": verdict_for(overall, critical),
        "category_scores": _derive_categories(report.category_scores, [q.score for q in questions], critical),
    })


async def _score_once(
    provider: LLMProvider, system: str, questions: Sequence[str] = (), note: str = ""
) -> Report:
    """chat_json -> validated Report. One retry with a 'fix it' instruction; ReportParseError if that fails too."""
    base = [ChatMessage(role="user", content=EVALUATE_TEXT + (f" Fix these problems from your earlier attempt: {note}" if note else ""))]
    problem = ""
    previous: dict[str, Any] | None = None
    for attempt in (1, 2):
        messages = list(base)
        if attempt == 2:
            if previous is not None:
                messages.append(ChatMessage(role="assistant", content=json.dumps(previous, ensure_ascii=False)[:6000]))
            messages.append(ChatMessage(
                role="user",
                content=f"That reply was not valid ({problem}). Fix it: reply with ONLY one valid JSON object "
                "that matches the schema described in your instructions.",
            ))
        try:
            previous = await provider.chat_json(system, messages)
            report = finalize_report(_parse(previous))
            if questions and len(report.per_question) != len(questions) and attempt == 1:
                raise ValueError(f"per_question has {len(report.per_question)} items but exactly {len(questions)} "
                                 "main questions were asked: write exactly one item per main question")
            return fit_count(report, questions)
        except AppError as exc:
            if exc.code != "llm_bad_json":
                raise  # provider down / not configured: do not save a fake report
            problem, previous = "not valid JSON", None
        except (ValidationError, ValueError, TypeError) as exc:
            problem = str(exc)[:300]
        logger.warning("report_parse_failed", extra={"attempt": attempt})
    raise ReportParseError(problem)


def _dedupe(lists: Sequence[Sequence[str]], cap: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for items in lists:
        for item in items:
            key = " ".join(item.lower().split())
            if key and key not in seen:
                seen.add(key)
                out.append(item)
    return out[:cap]


async def _merge_summary(provider: LLMProvider, reports: Sequence[Report], role_name: str, level: str) -> str:
    system = render("eval_merge", role_name=role_name, level=level, summaries="\n".join(f"- {r.summary}" for r in reports))
    try:
        data = await provider.chat_json(system, [ChatMessage(role="user", content="Merge the summaries now.")])
        summary = str(data.get("summary", "")).strip()
        if summary:
            return summary[:1500]
    except AppError:
        pass
    logger.warning("summary_merge_failed")
    return reports[0].summary


async def merge_reports(
    provider: LLMProvider, reports: Sequence[Report], role_name: str, level: str, questions: Sequence[str] = ()
) -> Report:
    """Average scores, union + de-duplicate lists, one extra call for a single summary.

    A question counts as having a critical mistake (or needing prompting) when any panel member said so; the caps and
    the overall score are then applied again by finalize_report.
    """
    if len(reports) == 1:
        return reports[0]
    if questions:  # members with the right number of items first, so the wording comes from a complete report
        reports = sorted(reports, key=lambda r: len(r.per_question) != len(questions))
    cats = [r.category_scores for r in reports]
    category = CategoryScores(**{f: _mean([getattr(c, f) for c in cats]) for f in CategoryScores.model_fields})
    base = reports[0].per_question
    per_question: list[PerQuestion] = []
    for i, q in enumerate(base):  # aligned by position; the first report provides the wording
        peers = [r.per_question[i] for r in reports if i < len(r.per_question)]
        per_question.append(q.model_copy(update={
            "score": _mean([p.score for p in peers]),
            "critical_mistake": any(p.critical_mistake for p in peers),
            "needed_prompting": any(p.needed_prompting for p in peers),
        }))
    lists = {name: _dedupe([getattr(r, name) for r in reports], cap) for name, cap in MERGED_LIST_CAPS.items()}
    merged = Report(
        overall_score=_mean([r.overall_score for r in reports]),
        category_scores=category,
        summary=await _merge_summary(provider, reports, role_name, level),
        per_question=per_question,
        **lists,
    )
    return fit_count(finalize_report(merged), questions)


async def generate_report(
    role_name: str, level: str, interview_type: str, transcript: str,
    answers: Sequence[str] | None = None, questions: Sequence[str] = (),
    prompted: Sequence[bool] | None = None, injection_at: int | None = None, topic_text: str = "",
) -> Report:
    """Evaluate a transcript. Provider outages raise AppError; unusable model output gives a fallback report.

    `questions` (the real main questions) and `answers` (candidate text per question) let the code check the item
    count and apply apply_code_rules; without them the model's report is only finalized.
    """
    provider = get_provider()
    base = dict(role_name=role_name, level=level, interview_type=interview_type, transcript=transcript,
                asked=len(questions))
    try:
        if not get_settings().ENABLE_PARALLEL_EVAL:
            report = await _score_once(provider, render("evaluator", **base), questions)
        else:
            results = await asyncio.gather(
                *(_score_once(provider, render("evaluator", **base, focus=f), questions) for f in PERSPECTIVES.values()),
                return_exceptions=True,
            )
            reports = [r for r in results if isinstance(r, Report)]
            if not reports:
                outage = next((r for r in results if isinstance(r, AppError)), None)
                if outage is not None:
                    raise outage
                raise ReportParseError("all perspectives failed")
            report = await merge_reports(provider, reports, role_name, level, questions)
    except ReportParseError:
        logger.error("report_fallback_used")
        return fallback_report()
    if (problems := find_contradictions(report)) and not report.is_fallback:
        try:  # one more try with the contradictions named; the better of the two reports is kept
            again = await _score_once(provider, render("evaluator", **base), questions, "; ".join(problems))
            if len(find_contradictions(again)) < len(problems):
                report = again
        except (ReportParseError, AppError):
            logger.warning("report_recheck_failed")
    if answers is not None:
        report = apply_code_rules(report, answers, transcript, prompted, level, injection_at, topic_text)
    if questions and len(report.per_question) == len(questions):  # the question text is the stored one, never the model's copy
        report = report.model_copy(update={"per_question": [
            q.model_copy(update={"question": text[:300]}) for q, text in zip(report.per_question, questions, strict=True)]})
    if problems := check_report_invariants(report, len(questions) or None):
        logger.warning("report_invariants_failed", extra={"problems": problems})
    return report


def to_feedback(session_id: uuid.UUID, report: Report) -> Feedback:
    """Report -> `feedback` row. `tips` JSON holds improvement_tips, recommended_topics and the fallback flag."""
    return Feedback(
        session_id=session_id,
        overall_score=report.overall_score,
        category_scores=report.category_scores.model_dump(),
        strengths=report.strengths,
        weaknesses=report.weaknesses,
        per_question=[q.model_dump() for q in report.per_question],
        tips={
            "improvement_tips": report.improvement_tips,
            "recommended_topics": report.recommended_topics,
            "is_fallback": report.is_fallback,
        },
        summary=report.summary,
    )


def from_feedback(fb: Feedback) -> Report:
    tips = fb.tips if isinstance(fb.tips, dict) else {"improvement_tips": list(fb.tips or [])}
    critical = any(isinstance(q, dict) and q.get("critical_mistake") for q in (fb.per_question or []))
    return Report.model_validate({
        "verdict": verdict_for(fb.overall_score, critical),
        "has_critical": critical,
        "overall_score": fb.overall_score,
        "category_scores": fb.category_scores,
        "summary": fb.summary,
        "strengths": fb.strengths,
        "weaknesses": fb.weaknesses,
        "per_question": fb.per_question,
        "improvement_tips": tips.get("improvement_tips", []),
        "recommended_topics": tips.get("recommended_topics", []),
        "is_fallback": bool(tips.get("is_fallback", False)),
    })
