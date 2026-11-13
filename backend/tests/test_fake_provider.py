import pytest

from app.core.errors import AppError
from app.services.llm import ChatMessage, ToolSpec, get_provider
from tests.conftest import FakeProvider, tool_call, tool_response

MSG = [ChatMessage(role="user", content="hi")]


async def test_fake_provider_scripts_text_json_and_tools() -> None:
    fake = FakeProvider(
        texts=["Hello there candidate"],
        jsons=[{"overall_score": 70}],
        tool_responses=[tool_response(tool_call("end_interview", reason="done")), "plain answer"],
    )
    assert "".join([c async for c in fake.stream_chat("sys", MSG)]) == "Hello there candidate"
    assert await fake.chat_json("sys", MSG, schema={"type": "object"}) == {"overall_score": 70}
    tools = [ToolSpec("end_interview", "end", {"type": "object", "properties": {}})]
    first = await fake.chat_with_tools("sys", MSG, tools)
    assert first.tool_calls[0].name == "end_interview" and first.tool_calls[0].arguments == {"reason": "done"}
    assert (await fake.chat_with_tools("sys", MSG, tools)).text == "plain answer"
    assert [c["method"] for c in fake.calls] == ["stream_chat", "chat_json", "chat_with_tools", "chat_with_tools"]


async def test_fake_provider_raises_scripted_errors_and_when_empty() -> None:
    fake = FakeProvider(jsons=[AppError("llm_bad_json", "bad", 502)])
    with pytest.raises(AppError):
        await fake.chat_json("s", MSG)
    with pytest.raises(AssertionError):
        await fake.chat_json("s", MSG)


def test_use_fake_llm_overrides_get_provider(use_fake_llm) -> None:  # type: ignore[no-untyped-def]
    provider = use_fake_llm(texts=["x"])
    assert get_provider() is provider
