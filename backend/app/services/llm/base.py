import json
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import AppError

CHAT_TEMPERATURE = 0.7
TOOLS_TEMPERATURE = 0.5
JSON_TEMPERATURE = 0.2
BEGIN_TURN_TEXT = "Begin."  # sent when the conversation has no user turn yet (e.g. interviewer's opening message)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    extra: dict[str, Any] | None = None  # opaque provider data to echo back (e.g. Gemini thought_signature)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments, "extra": self.extra}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(id=data["id"], name=data["name"], arguments=data.get("arguments") or {}, extra=data.get("extra"))


@dataclass(frozen=True)
class ChatMessage:
    role: str  # user | assistant | tool (| system, folded into the system prompt by adapters)
    content: str = ""
    tool_calls: list[ToolCall] | None = None  # on assistant messages that requested tools
    tool_call_id: str | None = None  # on tool messages: the ToolCall.id being answered
    name: str | None = None  # on tool messages: the tool name


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (type: object)


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens, total_tokens


class LLMProvider(ABC):
    """Provider-agnostic interface. Callers never see Gemini/Groq specifics."""

    @abstractmethod
    def stream_chat(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield text chunks as they are generated."""

    @abstractmethod
    async def chat_json(
        self, system: str, messages: Sequence[ChatMessage], schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return one parsed JSON object. Raises AppError llm_bad_json (502) if the reply is not valid JSON."""

    @abstractmethod
    async def chat_with_tools(
        self, system: str, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        """One non-streaming turn that may return tool calls."""


# ---------- helpers shared by adapters ----------

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*[ \t]*\r?\n?(.*?)\r?\n?```\s*$", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def strip_thinking(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Strip <think> blocks and code fences, then parse a JSON object or raise AppError llm_bad_json (502)."""
    cleaned = strip_thinking(text)
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        candidates.append(cleaned[start : end + 1])  # drop prose around the object
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise AppError("llm_bad_json", "The AI returned an invalid response. Please try again.", 502)


def prepare(
    system: str, messages: Sequence[ChatMessage], *, json_mode: bool = False, schema: dict[str, Any] | None = None
) -> tuple[str, list[ChatMessage]]:
    """Fold system-role messages and JSON/schema instructions into the system text; guarantee a user turn exists."""
    system_parts = [system] if system else []
    rest: list[ChatMessage] = []
    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
        else:
            rest.append(m)
    if json_mode:
        hint = "Reply with a single valid JSON object and nothing else (no code fences, no commentary)."
        if schema:
            hint += "\nThe object MUST match this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
        system_parts.append(hint)
    if not any(m.role == "user" for m in rest):
        rest.insert(0, ChatMessage(role="user", content=BEGIN_TURN_TEXT))
    return "\n\n".join(system_parts), rest


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:16]}"
