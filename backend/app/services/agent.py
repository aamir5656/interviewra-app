import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from app.core.sse import sse_event
from app.services.question_text import extract_question, split_question, strip_q_tags
from app.services.llm.base import ChatMessage, LLMProvider, ToolSpec
from app.services.tools import TOOL_LABELS, ToolContext, execute_tool

logger = logging.getLogger("app.agent")
WORDS_PER_CHUNK = 3
CHUNK_DELAY_SECONDS = 0.01  # small pause so the text feels streamed
MAX_EMPTY_REPLIES = 1
FALLBACK_REPLY = "Could you give one specific example or detail from your own experience?"
FALLBACK_CLOSING = "Thank you for your time. That brings us to the end of the interview, and your report is being prepared."


@dataclass
class AgentResult:
    text: str = ""
    steps: int = 0
    used_fallback: bool = False


async def _stream_text(text: str) -> AsyncIterator[str]:
    words = re.findall(r"\S+\s*", text)
    for i in range(0, len(words), WORDS_PER_CHUNK):
        yield sse_event("token", {"text": "".join(words[i : i + WORDS_PER_CHUNK])})
        await asyncio.sleep(CHUNK_DELAY_SECONDS)


def _store_question(ctx: ToolContext, text: str) -> str:
    """Save the exact question with this turn's main-question record and return the text to show (no tags).

    The question is what the model put inside <q></q>; without tags it is the best guess from the text. Turns that do not
    ask a new main question (follow-ups, repeats, the closing) only lose stray tags.
    """
    entry = next((c for c in reversed(ctx.calls) if c.get("name") == "get_next_topic"), None)
    if entry is None:
        return strip_q_tags(text)
    shown, question = split_question(text)
    entry["arguments"] = {**(entry.get("arguments") or {}), "question": question or extract_question(shown)}
    return shown


async def _enforce(
    provider: LLMProvider, system: str, convo: list[ChatMessage], text: str, closing: bool,
    check: Callable[[str, bool], list[str]], clean: Callable[[str], str] | None,
) -> str:
    """Code check of the reply. If it breaks a rule, the model rewrites it ONCE (no tools); then code cleans it up."""
    problems = check(text, closing)
    if problems:
        logger.info("reply_rewrite", extra={"problems": problems})
        convo = [*convo, ChatMessage(role="assistant", content=text), ChatMessage(
            role="user", content="Rewrite your last reply. It broke these rules: " + "; ".join(problems)
            + ". Reply with ONLY the corrected message to the candidate.")]
        try:
            retry = (await provider.chat_with_tools(system, convo, [])).text or ""
        except Exception:  # noqa: BLE001 - a failed rewrite must not break the turn
            logger.warning("reply_rewrite_failed", exc_info=True)
            retry = ""
        if retry.strip():
            text = retry.strip()
    return clean(text) if clean is not None else text


async def run_agent_turn(
    provider: LLMProvider,
    ctx: ToolContext,
    system: str,
    messages: Sequence[ChatMessage],
    tools: Sequence[ToolSpec],
    result: AgentResult,
    *,
    max_steps: int,
    wrap_up: bool = False,
    check: Callable[[str, bool], list[str]] | None = None,
    clean: Callable[[str], str] | None = None,
    fallback: str | None = None,
) -> AsyncIterator[str]:
    """One interviewer turn as SSE strings (`tool_event`, `token`); the final text is also left in `result.text`.

    Loop (at most `max_steps` model calls): the model may request tools; independent calls run in parallel with
    asyncio.gather and their results go back to the model. Plain text ends the loop and is streamed to the client.
    If the steps run out, a graceful fallback reply is used. On the wrap-up turn the interview is always ended.
    """
    convo = list(messages)
    empty = 0
    for step in range(1, max_steps + 1):
        result.steps = step
        resp = await provider.chat_with_tools(system, convo, tools)
        names = [c.name for c in resp.tool_calls]
        logger.info("agent_step", extra={"step": step, "tool_calls": names, "text_chars": len(resp.text or "")})

        if resp.tool_calls:
            convo.append(ChatMessage(role="assistant", content=resp.text or "", tool_calls=list(resp.tool_calls)))
            for call in resp.tool_calls:
                yield sse_event("tool_event", {"name": call.name, "label": TOOL_LABELS.get(call.name, "Working")})
            outputs = await asyncio.gather(*(execute_tool(ctx, c) for c in resp.tool_calls))
            for call, out in zip(resp.tool_calls, outputs):
                logger.info("agent_tool", extra={"step": step, "tool": call.name, "ok": "error" not in out})
                convo.append(ChatMessage(
                    role="tool", content=json.dumps(out, ensure_ascii=False), tool_call_id=call.id, name=call.name
                ))
            if ctx.ended and (resp.text or "").strip():  # ctx.ended is set only by an end_interview call that was allowed
                result.text = resp.text.strip()  # the thank-you came with the end call: nothing more to ask the model
                break
            continue

        text = (resp.text or "").strip()
        if text:
            result.text = text
            break
        empty += 1
        if empty > MAX_EMPTY_REPLIES:
            break

    if not result.text:
        result.used_fallback = True
        result.text = FALLBACK_CLOSING if ctx.ended or wrap_up else (fallback or FALLBACK_REPLY)
        logger.warning("agent_fallback", extra={"steps": result.steps})
    if check is not None and not result.used_fallback:
        result.text = await _enforce(provider, system, convo, result.text, ctx.ended or wrap_up, check, clean)
    result.text = _store_question(ctx, result.text)
    if wrap_up and not ctx.ended:
        ctx.ended, ctx.end_reason = True, "ended by server after the final answer"
        ctx.calls.append({"name": "end_interview", "arguments": {"reason": ctx.end_reason}})  # stored: blocks more answers
        logger.info("agent_forced_end")
    async for ev in _stream_text(result.text):
        yield ev
