import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.services.llm.base import (
    CHAT_TEMPERATURE, JSON_TEMPERATURE, TOOLS_TEMPERATURE, ChatMessage, LLMResponse, ToolCall, ToolSpec,
    new_call_id, parse_json_object, prepare,
)
from app.services.llm.http_provider import HTTPProvider

_SCHEMA_KEYS = {
    "type", "description", "properties", "required", "items", "enum", "format", "nullable",
    "minimum", "maximum", "minItems", "maxItems",
}


def _clean_schema(schema: Any) -> Any:
    """Gemini accepts an OpenAPI subset: drop keys such as additionalProperties / $schema / default."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: _clean_schema(sub) for name, sub in value.items()}
            elif key in _SCHEMA_KEYS:
                out[key] = _clean_schema(value)
        return out
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema


def _function_response(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except ValueError:
        return {"result": content}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


class GeminiProvider(HTTPProvider):
    """Google Gemini REST API (generativelanguage.googleapis.com, v1beta)."""

    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}  # key in header, never in URL

    def _url(self, method: str, stream: bool = False) -> str:
        model = self.model.removeprefix("models/")
        return f"{self.BASE_URL}/models/{model}:{method}" + ("?alt=sse" if stream else "")

    @staticmethod
    def _contents(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def push(role: str, parts: list[dict[str, Any]]) -> None:
            if out and out[-1]["role"] == role:  # Gemini wants tool results of one turn merged
                out[-1]["parts"].extend(parts)
            else:
                out.append({"role": role, "parts": parts})

        for m in messages:
            if m.role == "user":
                push("user", [{"text": m.content or "(empty message)"}])
            elif m.role == "assistant":
                parts: list[dict[str, Any]] = [{"text": m.content}] if m.content else []
                for tc in m.tool_calls or []:
                    part: dict[str, Any] = {"functionCall": {"name": tc.name, "args": tc.arguments}}
                    if tc.extra and tc.extra.get("thought_signature"):
                        part["thoughtSignature"] = tc.extra["thought_signature"]
                    parts.append(part)
                if parts:
                    push("model", parts)
            elif m.role == "tool":
                push("user", [{"functionResponse": {"name": m.name or "tool", "response": _function_response(m.content)}}])
        return out

    def _payload(
        self,
        system: str,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        tools: Sequence[ToolSpec] | None = None,
        json_mode: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_text, rest = prepare(system, messages, json_mode=json_mode, schema=schema)
        payload: dict[str, Any] = {
            "contents": self._contents(rest),
            "generationConfig": {"temperature": temperature},
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if tools:
            declarations = []
            for tool in tools:
                decl: dict[str, Any] = {"name": tool.name, "description": tool.description}
                params = _clean_schema(tool.parameters)
                if params.get("properties"):  # Gemini rejects object schemas without properties
                    decl["parameters"] = params
                declarations.append(decl)
            payload["tools"] = [{"functionDeclarations": declarations}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        return payload

    @staticmethod
    def _parts(data: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = data.get("candidates") or []
        if not candidates:
            return []
        return [p for p in (candidates[0].get("content") or {}).get("parts") or [] if not p.get("thought")]

    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        parts = self._parts(data)
        text = "".join(p["text"] for p in parts if isinstance(p.get("text"), str))
        calls: list[ToolCall] = []
        for p in parts:
            fc = p.get("functionCall")
            if fc and fc.get("name"):
                extra = {"thought_signature": p["thoughtSignature"]} if p.get("thoughtSignature") else None
                calls.append(ToolCall(fc.get("id") or new_call_id(), fc["name"], fc.get("args") or {}, extra))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            tool_calls=calls,
            usage={
                "prompt_tokens": int(usage.get("promptTokenCount", 0)),
                "completion_tokens": int(usage.get("candidatesTokenCount", 0)),
                "total_tokens": int(usage.get("totalTokenCount", 0)),
            },
        )

    async def stream_chat(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        payload = self._payload(system, messages, temperature=CHAT_TEMPERATURE)
        async for event in self._stream_events(self._url("streamGenerateContent", stream=True), payload):
            text = "".join(p["text"] for p in self._parts(event) if isinstance(p.get("text"), str))
            if text:
                yield text

    async def chat_json(
        self, system: str, messages: Sequence[ChatMessage], schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self._payload(system, messages, temperature=JSON_TEMPERATURE, json_mode=True, schema=schema)
        return parse_json_object(self._parse(await self._post_json(self._url("generateContent"), payload)).text)

    async def chat_with_tools(
        self, system: str, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        payload = self._payload(system, messages, temperature=TOOLS_TEMPERATURE, tools=tools)
        return self._parse(await self._post_json(self._url("generateContent"), payload))
