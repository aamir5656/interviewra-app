import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.services.llm.base import (
    CHAT_TEMPERATURE, JSON_TEMPERATURE, TOOLS_TEMPERATURE, ChatMessage, LLMResponse, ToolCall, ToolSpec,
    new_call_id, parse_json_object, prepare, strip_thinking,
)
from app.services.llm.http_provider import HTTPProvider
from app.services.llm.retry import FatalError, RetryableError

logger = logging.getLogger("app.llm")


class GroqProvider(HTTPProvider):
    """Groq (OpenAI-compatible chat completions API)."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _classify(self, status: int, body: str, headers: httpx.Headers) -> RetryableError | FatalError:
        if status == 400 and "tool_use_failed" in body:  # model produced a malformed tool call: sampling is random, retry
            return RetryableError("tool_use_failed")
        return super()._classify(status, body, headers)

    @staticmethod
    def _messages(system: str, messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content or "(empty message)"})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in m.tool_calls
                    ]
                if msg["content"] or m.tool_calls:
                    out.append(msg)
            elif m.role == "tool":
                tool_msg: dict[str, Any] = {"role": "tool", "tool_call_id": m.tool_call_id or m.name or "call", "content": m.content}
                if m.name:
                    tool_msg["name"] = m.name
                out.append(tool_msg)
        return out

    def _payload(
        self,
        system: str,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        stream: bool = False,
        tools: Sequence[ToolSpec] | None = None,
        json_mode: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_text, rest = prepare(system, messages, json_mode=json_mode, schema=schema)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system_text, rest),
            "temperature": temperature,
        }
        if stream:
            payload["stream"] = True
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices") or []
        message = (choices[0].get("message") if choices else None) or {}
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            if not fn.get("name"):
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                logger.warning("llm_bad_tool_arguments", extra={"provider": "groq", "tool": fn["name"]})
                args = {}
            calls.append(ToolCall(raw.get("id") or new_call_id(), fn["name"], args if isinstance(args, dict) else {}))
        usage = data.get("usage") or {}
        return LLMResponse(
            text=strip_thinking(message.get("content") or ""),
            tool_calls=calls,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
        )

    async def stream_chat(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        payload = self._payload(system, messages, temperature=CHAT_TEMPERATURE, stream=True)
        async for event in self._stream_events(self.URL, payload):
            for choice in event.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text

    async def chat_json(
        self, system: str, messages: Sequence[ChatMessage], schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self._payload(system, messages, temperature=JSON_TEMPERATURE, json_mode=True, schema=schema)
        return parse_json_object(self._parse(await self._post_json(self.URL, payload)).text)

    async def chat_with_tools(
        self, system: str, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        payload = self._payload(system, messages, temperature=TOOLS_TEMPERATURE, tools=tools)
        return self._parse(await self._post_json(self.URL, payload))
