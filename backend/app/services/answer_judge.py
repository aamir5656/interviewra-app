"""A small model call that spots wrong or unprofessional answers that no regex can see.

The code (not the model) then decides what happens: a wrong answer gets exactly one follow-up on the same question and
the interview cannot move on in that turn (see routers/interview.py). Any problem here keeps the old behaviour.
"""
import logging
from typing import Any

from app.services.llm.base import ChatMessage, LLMProvider
from app.services.prompts import render

logger = logging.getLogger("app.judge")
MAX_AREA_CHARS = 80
BAD_VERDICTS = frozenset({"wrong", "unprofessional"})


def parse_verdict(data: Any) -> tuple[str, str]:
    """(verdict, area) from the model's JSON; anything unexpected counts as \"correct\" (no follow-up is forced)."""
    if not isinstance(data, dict):
        return "correct", ""
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in BAD_VERDICTS | {"partly", "correct"}:
        return "correct", ""
    area = " ".join(str(data.get("area", "") or "").split())[:MAX_AREA_CHARS] if verdict in BAD_VERDICTS else ""
    return verdict, area


async def judge_answer(
    provider: LLMProvider, *, role_name: str, level: str, qtype: str | None, question: str, answer: str
) -> tuple[str, str]:
    """Returns (\"wrong\" | \"ok\", area). Never raises: a failed call means no extra follow-up."""
    try:
        system = render("answer_judge", role_name=role_name, level=level, qtype=qtype or "technical",
                        question=question or "(question text not available)", answer=answer[:4000])
        data = await provider.chat_json(system, [ChatMessage(role="user", content="Judge the answer now.")])
    except Exception:  # noqa: BLE001 - the judge is a helper; the interview must go on without it
        logger.warning("answer_judge_failed", exc_info=True)
        return "ok", ""
    verdict, area = parse_verdict(data)
    logger.info("answer_judged", extra={"verdict": verdict})
    return ("wrong", area) if verdict in BAD_VERDICTS else ("ok", "")
