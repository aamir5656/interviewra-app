import json
from collections.abc import Callable

import httpx
import pytest

from app.config import get_settings
from app.core.errors import AppError
from app.services.llm import ChatMessage, GeminiProvider, GroqProvider, ToolCall, ToolSpec, get_provider
from app.services.llm.base import parse_json_object

TOOLS = [ToolSpec("get_next_topic", "Next topic", {"type": "object", "properties": {"hint": {"type": "string"}}, "additionalProperties": False})]
HISTORY = [
    ChatMessage(role="user", content="My answer"),
    ChatMessage(role="assistant", content="", tool_calls=[ToolCall("c1", "get_next_topic", {"hint": "x"}, {"thought_signature": "sig"})]),
    ChatMessage(role="tool", content='{"topic": "SQL"}', tool_call_id="c1", name="get_next_topic"),
]


class Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses, self.requests, self.sleeps = list(responses), [], []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

        return httpx.MockTransport(handler)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


def gemini(rec: Recorder) -> GeminiProvider:
    return GeminiProvider("KEY", "models/test-model", 5, transport=rec.transport(), sleep=rec.sleep)


def groq(rec: Recorder) -> GroqProvider:
    return GroqProvider("KEY", "test-model", 5, transport=rec.transport(), sleep=rec.sleep)


def gem_text(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5}})


def groq_text(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})


# ---------- JSON mode ----------


@pytest.mark.parametrize("raw", ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here you go:\n{"a": 1}', '<think>hmm</think>{"a": 1}'])
def test_parse_json_object_variants(raw: str) -> None:
    assert parse_json_object(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", ""])
def test_parse_json_object_failure(raw: str) -> None:
    with pytest.raises(AppError) as e:
        parse_json_object(raw)
    assert e.value.code == "llm_bad_json" and e.value.status_code == 502


async def test_gemini_chat_json_request_and_parse() -> None:
    rec = Recorder(gem_text('```json\n{"score": 5}\n```'))
    out = await gemini(rec).chat_json("SYS", [ChatMessage(role="user", content="q")], schema={"type": "object"})
    assert out == {"score": 5}
    req, body = rec.requests[0], rec.body(0)
    assert req.url.path.endswith("/models/test-model:generateContent") and req.headers["x-goog-api-key"] == "KEY"
    assert "KEY" not in str(req.url)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "JSON Schema" in body["systemInstruction"]["parts"][0]["text"]


async def test_groq_chat_json_request_and_parse() -> None:
    rec = Recorder(groq_text('{"score": 7}'))
    assert await groq(rec).chat_json("SYS", [ChatMessage(role="user", content="q")]) == {"score": 7}
    body = rec.body(0)
    assert rec.requests[0].headers["authorization"] == "Bearer KEY"
    assert body["response_format"] == {"type": "json_object"} and body["model"] == "test-model"
    assert body["messages"][0]["role"] == "system" and "JSON" in body["messages"][0]["content"]


@pytest.mark.parametrize("factory,resp", [(gemini, gem_text), (groq, groq_text)])
async def test_bad_json_raises_502(factory: Callable, resp: Callable) -> None:
    with pytest.raises(AppError) as e:
        await factory(Recorder(resp("definitely not json"))).chat_json("s", [ChatMessage(role="user", content="q")])
    assert e.value.code == "llm_bad_json" and e.value.status_code == 502


# ---------- tools ----------


async def test_gemini_tools_roundtrip() -> None:
    reply = httpx.Response(200, json={"candidates": [{"content": {"parts": [
        {"text": "Thinking aloud", "thought": True},
        {"functionCall": {"name": "get_next_topic", "args": {"hint": "api"}}, "thoughtSignature": "sig2"},
    ]}}]})
    rec = Recorder(reply)
    res = await gemini(rec).chat_with_tools("SYS", HISTORY, TOOLS)
    assert res.text == "" and res.tool_calls[0].name == "get_next_topic" and res.tool_calls[0].arguments == {"hint": "api"}
    assert res.tool_calls[0].id.startswith("call_") and res.tool_calls[0].extra == {"thought_signature": "sig2"}
    body = rec.body(0)
    decl = body["tools"][0]["functionDeclarations"][0]
    assert decl["name"] == "get_next_topic" and "additionalProperties" not in decl["parameters"]
    model_part = body["contents"][1]["parts"][0]
    assert model_part["functionCall"]["name"] == "get_next_topic" and model_part["thoughtSignature"] == "sig"
    assert body["contents"][2] == {"role": "user", "parts": [{"functionResponse": {"name": "get_next_topic", "response": {"topic": "SQL"}}}]}


async def test_groq_tools_roundtrip() -> None:
    reply = httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "abc", "type": "function", "function": {"name": "get_next_topic", "arguments": '{"hint": "api"}'}}]}}]})
    rec = Recorder(reply)
    res = await groq(rec).chat_with_tools("SYS", HISTORY, TOOLS)
    assert res.tool_calls == [ToolCall("abc", "get_next_topic", {"hint": "api"})] and res.text == ""
    body = rec.body(0)
    assert body["tools"][0]["function"]["name"] == "get_next_topic" and body["tool_choice"] == "auto"
    assistant, tool = body["messages"][2], body["messages"][3]
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"hint": "x"}'
    assert tool["role"] == "tool" and tool["tool_call_id"] == "c1"


async def test_empty_conversation_gets_a_user_turn() -> None:
    rec = Recorder(gem_text("Hi"))
    await gemini(rec).chat_with_tools("SYS", [], [])
    assert rec.body(0)["contents"] == [{"role": "user", "parts": [{"text": "Begin."}]}]


# ---------- streaming ----------


async def test_gemini_stream() -> None:
    sse = 'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}\r\n\r\ndata: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}\n\n'
    rec = Recorder(httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"}))
    chunks = [c async for c in gemini(rec).stream_chat("s", [ChatMessage(role="user", content="q")])]
    assert chunks == ["Hel", "lo"] and "streamGenerateContent" in str(rec.requests[0].url) and "alt=sse" in str(rec.requests[0].url)


async def test_groq_stream() -> None:
    sse = 'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\ndata: {"choices":[{"delta":{"content":"Hi "}}]}\n\ndata: {"choices":[{"delta":{"content":"there"}}]}\n\ndata: [DONE]\n\n'
    rec = Recorder(httpx.Response(200, content=sse.encode()))
    assert [c async for c in groq(rec).stream_chat("s", [ChatMessage(role="user", content="q")])] == ["Hi ", "there"]
    assert rec.body(0)["stream"] is True


# ---------- retry / timeout ----------


async def test_retries_429_and_5xx_then_succeeds() -> None:
    rec = Recorder(httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(503), groq_text('{"ok": true}'))
    assert await groq(rec).chat_json("s", [ChatMessage(role="user", content="q")]) == {"ok": True}
    assert len(rec.requests) == 3 and len(rec.sleeps) == 2 and 1.0 <= rec.sleeps[0] < 1.2 and rec.sleeps[1] >= 1.0


async def test_exhausted_retries_raise_llm_unavailable() -> None:
    rec = Recorder(httpx.Response(500))
    with pytest.raises(AppError) as e:
        await gemini(rec).chat_with_tools("s", [ChatMessage(role="user", content="q")], [])
    assert e.value.code == "llm_unavailable" and e.value.status_code == 503
    assert len(rec.requests) == 3 and len(rec.sleeps) == 2


async def test_timeout_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    rec = Recorder()
    provider = GroqProvider("KEY", "m", 5, transport=httpx.MockTransport(handler), sleep=rec.sleep)
    with pytest.raises(AppError) as e:
        await provider.chat_with_tools("s", [ChatMessage(role="user", content="q")], [])
    assert e.value.code == "llm_unavailable" and calls == 3


async def test_fatal_status_not_retried() -> None:
    rec = Recorder(httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(AppError) as e:
        await groq(rec).chat_json("s", [ChatMessage(role="user", content="q")])
    assert e.value.status_code == 503 and len(rec.requests) == 1


async def test_groq_tool_use_failed_is_retried() -> None:
    rec = Recorder(httpx.Response(400, json={"error": {"code": "tool_use_failed"}}), groq_text("ok"))
    assert (await groq(rec).chat_with_tools("s", [ChatMessage(role="user", content="q")], TOOLS)).text == "ok"
    assert len(rec.requests) == 2


async def test_stream_retries_before_first_token() -> None:
    sse = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    rec = Recorder(httpx.Response(503), httpx.Response(200, content=sse.encode()))
    assert [c async for c in groq(rec).stream_chat("s", [ChatMessage(role="user", content="q")])] == ["ok"]
    assert len(rec.requests) == 2


# ---------- factory ----------


def test_get_provider_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "LLM_API_KEY", "k")
    monkeypatch.setattr(s, "LLM_MODEL", "some-model")
    monkeypatch.setattr(s, "LLM_PROVIDER", "Groq")
    p = get_provider()
    assert isinstance(p, GroqProvider) and p.model == "some-model" and p.timeout == float(s.LLM_TIMEOUT_SECONDS)
    monkeypatch.setattr(s, "LLM_PROVIDER", "gemini")
    assert isinstance(get_provider(), GeminiProvider)


@pytest.mark.parametrize("provider,key,model", [("nope", "k", "m"), ("gemini", "", "m"), ("groq", "k", "")])
def test_get_provider_not_configured(monkeypatch: pytest.MonkeyPatch, provider: str, key: str, model: str) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", provider)
    monkeypatch.setattr(s, "LLM_API_KEY", key)
    monkeypatch.setattr(s, "LLM_MODEL", model)
    with pytest.raises(AppError) as e:
        get_provider()
    assert e.value.code == "llm_not_configured" and e.value.status_code == 503
