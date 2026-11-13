import asyncio
import json
import logging
import random
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update

from app.database import SessionFactory
from app.models import InterviewSession, InterviewType, Level
from app.services.llm.base import ToolCall, ToolSpec
from app.services.memory import compact_profile, load_profile

logger = logging.getLogger("app.tools")
BANK_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"
TOOL_LABELS = {
    "get_next_topic": "Choosing the next topic",
    "search_question_bank": "Looking up a question idea",
    "get_user_memory": "Recalling your past sessions",
    "end_interview": "Wrapping up your interview",
}
LEVEL_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3}
DIFFICULTY_RANK = {"easy": 0.0, "medium": 1.5, "hard": 3.0}
LEVEL_DIFFICULTY = {"intern": "easy", "junior": "easy", "mid": "medium", "senior": "hard"}
TRACK_KEYWORDS = {
    "backend": ("backend", "back-end", "back end", "api", "server", "python", "java", "node", "django", "fastapi",
                "golang", "go", ".net", "php", "ruby"),
    "frontend": ("frontend", "front-end", "front end", "react", "ui", "ux", "web", "javascript", "typescript", "css",
                 "angular", "vue", "next.js", "nextjs", "html"),
    "data": ("data", "ml", "machine learning", "analyst", "analytics", "scientist", "ai", "bi", "sql"),
    "devops": ("devops", "sre", "site reliability", "cloud", "infrastructure", "platform", "kubernetes", "sysadmin"),
    "qa": ("qa", "tester", "testing", "quality", "sdet", "test engineer"),
    "product": ("product", "pm", "project manager", "program manager", "business analyst", "scrum", "owner"),
}
DEV_TRACKS = frozenset({"backend", "frontend", "devops", "qa"})
FULLSTACK_WORDS = ("full-stack", "full stack", "fullstack")
RECENT_SESSIONS = 5  # topics from the user's last sessions are avoided when other topics exist
RECENT_PENALTY = 3.0
JITTER = 1.6  # how far from the level's difficulty a random pick may stray (0 = strict)
MIXED_ORDER = ("technical", "behavioral", "hr")  # fallback order when the preferred type has no topic left
# Mixed interviews open with an HR question (an introduction), then lean technical: about half technical,
# the rest behavioral and HR, and never two HR questions in a row.
MIXED_PATTERN = ("hr", "technical", "behavioral", "technical", "technical", "behavioral", "technical", "hr", "technical", "behavioral")
OPENING_HR_TOPIC = "Introduction"
MAX_SEARCH_RESULTS = 3


class ToolArgError(Exception):
    """The model sent invalid tool arguments; the message is returned to the model so it can retry."""


# ---------- context (server-side truth: the model never supplies user or session ids) ----------


@dataclass
class ToolContext:
    factory: SessionFactory
    session_id: uuid.UUID
    user_id: uuid.UUID
    is_registered: bool
    role_name: str
    level: str
    interview_type: str
    question_count: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # parallel tools never share one DB session concurrently
    ended: bool = False
    end_reason: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    # Result of the first get_next_topic call of this turn. A context lives for exactly one turn, so a second call in
    # the same turn (parallel or repeated) gets the same answer and does not count another main question.
    turn_topic: dict[str, Any] | None = None
    # Names of the tools offered this turn. When set, any other tool call is refused in code (the prompt alone cannot
    # stop the model from, for example, calling end_interview in the middle of the interview). None = no restriction.
    allowed_tools: frozenset[str] | None = None


# ---------- argument models ----------


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NextTopicArgs(_Args):
    role: str | None = Field(default=None, max_length=80)
    level: Level | None = None
    interview_type: InterviewType | None = None
    covered_topics: list[str] = Field(default_factory=list, max_length=30)  # advisory; the stored list is the truth


class SearchArgs(_Args):
    topic: str = Field(min_length=1, max_length=80)
    difficulty: Literal["easy", "medium", "hard"] | None = None


class EndArgs(_Args):
    reason: str = Field(default="interview completed", min_length=1, max_length=200)


class NoArgs(_Args):
    pass


_M = TypeVar("_M", bound=BaseModel)


def _validate(model: type[_M], raw: Any) -> _M:
    try:
        return model.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
        raise ToolArgError(f"invalid arguments ({problems})") from None


# ---------- question bank ----------


@lru_cache
def load_bank() -> list[dict[str, str]]:
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


def _tracks_for(role: str) -> set[str]:
    """Question-bank tracks that fit a role (whole-word match). Unknown roles get no track: general questions only."""
    r = role.lower()
    if any(w in r for w in FULLSTACK_WORDS):
        return {"backend", "frontend"}
    found = {t for t, words in TRACK_KEYWORDS.items() if any(_has_word(r, w) for w in words)}
    if not found and any(w in r for w in ("software", "developer", "engineer", "programmer")):
        return {"backend", "frontend"}
    return found


def _pool(
    role: str, level: str, interview_type: str, index: int, rng: random.Random | None = None,
    avoid: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    """Candidate questions for the next main question, best match first.

    Rank = distance between the question's difficulty and the level's difficulty, plus (with `rng`) a random jitter
    so sessions differ, plus a penalty for topics the user saw in recent sessions (`avoid`, normalised keys).
    The first question of a session and intern interviews stay strict on difficulty. Without `rng` the order is
    deterministic (bank order breaks ties).
    """
    bank = load_bank()
    tracks = _tracks_for(role)
    # "general" questions fit every role; "dev" questions (Git, code review, debugging...) only roles that write or run
    # code. A role that is not in the list (an old interview) keeps both, as before.
    allowed = {"general", *tracks}
    if not tracks or tracks & DEV_TRACKS:
        allowed.add("dev")
    if interview_type == "mixed":
        order = [MIXED_PATTERN[index % len(MIXED_PATTERN)], *MIXED_ORDER]
    else:
        order = [interview_type]
    target = DIFFICULTY_RANK[LEVEL_DIFFICULTY.get(level, "medium")]
    jitter = JITTER if (rng is not None and index > 0 and level != "intern") else 0.0
    out: list[dict[str, str]] = []
    for typ in dict.fromkeys(order):
        items = [q for q in bank if q["type"] == typ]
        if typ == "technical":
            items = [q for q in items if q["track"] in allowed] or items
        if rng is not None:
            rng.shuffle(items)

        def rank(q: dict[str, str]) -> float:
            r = abs(DIFFICULTY_RANK[q["difficulty"]] - target)
            if jitter:
                r += rng.random() * jitter  # type: ignore[union-attr]
            return r + (RECENT_PENALTY if _key(q["topic"]) in avoid else 0.0)

        items.sort(key=rank)
        if index == 0 and typ == "hr":  # an HR or mixed interview opens with the introduction
            items.sort(key=lambda q: _key(q["topic"]) != _key(OPENING_HR_TOPIC))
        out.extend(items)
    return out


def _key(topic: str) -> str:
    return " ".join(topic.lower().split())


# ---------- tool implementations ----------


async def get_next_topic(ctx: ToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    args = _validate(NextTopicArgs, raw)
    async with ctx.lock, ctx.factory() as s:
        if ctx.turn_topic is not None:  # second call in one turn: same topic, no extra main question
            return {**ctx.turn_topic, "note": "You already have this turn's topic and it is already counted. "
                    "Call get_next_topic at most once per turn, and only when you ask a brand-new main question."}
        row = (
            await s.execute(
                select(InterviewSession.covered_topics, InterviewSession.current_question_index,
                       InterviewSession.question_count)
                .where(InterviewSession.id == ctx.session_id, InterviewSession.user_id == ctx.user_id)
            )
        ).one_or_none()
        if row is None:
            return {"error": "session not found"}
        covered, index, total = list(row.covered_topics or []), row.current_question_index, row.question_count
        if index >= total:
            ctx.turn_topic = {"done": True}
            return {"done": True, "note": f"All {total} planned questions were asked. Do not ask another question: "
                    "thank the candidate and call end_interview."}
        role = args.role or ctx.role_name
        level = args.level.value if args.level else ctx.level
        itype = args.interview_type.value if args.interview_type else ctx.interview_type
        seen = {_key(t) for t in covered}
        rng = random.Random(f"{ctx.session_id}:{index}")  # varies between sessions, stable if a turn is retried
        recent = (await s.execute(
            select(InterviewSession.covered_topics)
            .where(InterviewSession.user_id == ctx.user_id, InterviewSession.id != ctx.session_id)
            .order_by(InterviewSession.created_at.desc()).limit(RECENT_SESSIONS)
        )).scalars().all()
        avoid = frozenset(_key(str(t)) for topics in recent for t in (topics or []))
        pick = next((q for q in _pool(role, level, itype, index, rng, avoid) if _key(q["topic"]) not in seen), None)
        if pick is None:
            await s.execute(  # the model must pick its own topic, and that question still counts
                update(InterviewSession).where(InterviewSession.id == ctx.session_id)
                .values(current_question_index=index + 1)
            )
            await s.commit()
            result: dict[str, Any] = {
                "topic": None, "question_number": index + 1, "total_questions": total,
                "main_questions_left_after_this": total - index - 1,
                "note": "The question bank has no uncovered topic left. Choose a fresh topic yourself that fits "
                "the role. It has already been counted as the next main question.",
            }
        else:
            await s.execute(
                update(InterviewSession).where(InterviewSession.id == ctx.session_id)
                .values(covered_topics=[*covered, pick["topic"]], current_question_index=index + 1)
            )
            await s.commit()
            result = {"topic": pick["topic"], "type": pick["type"], "difficulty": pick["difficulty"],
                      "question_idea": pick["question"], "question_number": index + 1, "total_questions": total,
                      "main_questions_left_after_this": total - index - 1}
        ctx.turn_topic = result
    logger.info("next_topic", extra={"question_number": index + 1, "total_questions": total,
                                     "topic_picked": result.get("topic")})
    return result


async def search_question_bank(ctx: ToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    args = _validate(SearchArgs, raw)
    wanted = args.difficulty or LEVEL_DIFFICULTY.get(ctx.level, "medium")
    needle = _key(args.topic)
    hits = [q for q in load_bank() if needle in _key(q["topic"]) or needle in _key(q["question"])]
    exact = [q for q in hits if q["difficulty"] == wanted]
    chosen = (exact or hits)[:MAX_SEARCH_RESULTS]
    if not chosen:
        return {"questions": [], "note": "No match in the bank. Write your own question for this topic."}
    return {"questions": [{"topic": q["topic"], "difficulty": q["difficulty"], "question": q["question"]} for q in chosen]}


async def get_user_memory(ctx: ToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    _validate(NoArgs, raw)
    if not ctx.is_registered:
        return {"profile": {}, "note": "Guest candidate: no saved history."}
    async with ctx.lock, ctx.factory() as s:
        profile = compact_profile(await load_profile(s, ctx.user_id))
    return {"profile": profile} if profile else {"profile": {}, "note": "No saved history yet."}


async def end_interview(ctx: ToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    args = _validate(EndArgs, raw)
    ctx.ended, ctx.end_reason = True, args.reason
    return {"status": "ready_for_evaluation", "note": "Interview marked complete. Say a short thank-you if you have not yet."}


_HANDLERS = {
    "get_next_topic": get_next_topic,
    "search_question_bank": search_question_bank,
    "get_user_memory": get_user_memory,
    "end_interview": end_interview,
}

_SPECS = {
    "get_next_topic": ToolSpec(
        "get_next_topic",
        "Pick the next uncovered topic. Call it at most ONCE per turn, and ONLY in the same turn where you ask a "
        "brand-new main question: it counts that question. NEVER call it when you ask a follow-up, give a hint, "
        "repeat a question, or ask for a real attempt after an 'I don't know', off-topic or instruction-style answer.",
        {"type": "object", "properties": {
            "role": {"type": "string"}, "level": {"type": "string", "enum": [e.value for e in Level]},
            "interview_type": {"type": "string", "enum": [e.value for e in InterviewType]},
            "covered_topics": {"type": "array", "items": {"type": "string"}}}},
    ),
    "search_question_bank": ToolSpec(
        "search_question_bank", "Fetch question ideas for a topic at a difficulty.",
        {"type": "object", "properties": {"topic": {"type": "string"},
                                          "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]}},
         "required": ["topic"]},
    ),
    "get_user_memory": ToolSpec(
        "get_user_memory", "Recall this candidate's strengths, weak topics and score trend from past sessions.",
        {"type": "object", "properties": {}},
    ),
    "end_interview": ToolSpec(
        "end_interview", "Finish the interview. Only available on the final turn, after the last planned question was answered.",
        {"type": "object", "properties": {"reason": {"type": "string"}}},
    ),
}


def tool_specs(
    *, wrap_up: bool, registered: bool, topic_chosen: bool = False, allow_end: bool = True
) -> list[ToolSpec]:
    """Tools offered for a turn.

    - wrap-up turn (the last planned question was answered): only end_interview;
    - every other turn: never end_interview, so the interview cannot stop early (the candidate has the End button);
    - topic_chosen: the server already picked this turn's main question, so get_next_topic is not offered;
    - allow_end=False on the last-question turn when the answer needs a retry or follow-up: no tools at all, so the
      model cannot end the interview before the candidate had that one more turn;
    - guests have no memory tool.
    """
    if wrap_up:
        return [_SPECS["end_interview"]] if allow_end else []
    hidden = {"end_interview"} | ({"get_next_topic"} if topic_chosen else set())
    return [s for n, s in _SPECS.items() if n not in hidden and (registered or n != "get_user_memory")]


async def choose_topic(ctx: ToolContext) -> dict[str, Any]:
    """The server picks and counts a new main question itself (same code path as the tool, recorded in ctx.calls)."""
    return await execute_tool(ctx, ToolCall(id="server-topic", name="get_next_topic", arguments={}))


async def execute_tool(ctx: ToolContext, call: ToolCall) -> dict[str, Any]:
    """Run one tool call. Never raises: problems come back as {"error": ...} for the model."""
    handler = _HANDLERS.get(call.name)
    if handler is not None and ctx.allowed_tools is not None and call.name not in ctx.allowed_tools:
        logger.warning("tool_not_offered", extra={"tool": call.name})
        result: dict[str, Any] = {"error": f"tool '{call.name}' is not available in this turn; continue without it"}
        return result  # not recorded: a refused call must never count as a main question or end the interview
    if handler is None:
        result = {"error": f"unknown tool '{call.name}'"}
    else:
        try:
            result = await handler(ctx, call.arguments or {})
        except ToolArgError as exc:
            result = {"error": str(exc)}
        except Exception:  # noqa: BLE001
            logger.exception("tool_failed", extra={"tool": call.name})
            result = {"error": "tool failed; continue without it"}
    ctx.calls.append({"name": call.name, "arguments": call.arguments or {}})
    return result
