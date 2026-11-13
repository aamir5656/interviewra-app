import copy
import os
import re
from collections import deque
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("STRICT_QUESTION_TAGS", "false")  # tag compliance is tested explicitly
os.environ.setdefault("ANSWER_JUDGE", "false")  # the extra judge call is tested explicitly; other tests script exact calls

from app.config import get_settings  # noqa: E402
from app.core.ratelimit import limiter
from app.database import get_db, get_session_factory
from app.main import create_app
from app.services.llm import set_provider_override
from app.services.llm.base import ChatMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec

# Tests run inside a transaction that is rolled back, so nothing is persisted.
# Tables must already exist (alembic upgrade head). Override with TEST_DATABASE_URL to use another DB.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or get_settings().DATABASE_URL


def pytest_report_header(config: pytest.Config) -> str | None:
    """A remote database (Neon) makes the suite very slow: every query is a network round trip."""
    host = TEST_DB_URL.split("@")[-1]
    if not any(h in host for h in ("localhost", "127.0.0.1", "host=/", "@/")):
        return ("WARNING: tests run against a remote database (slow, about 30 minutes). Start the local one with "
                "`docker compose up -d` and set TEST_DATABASE_URL to it (see README) to finish in about 1 minute.")
    return None


@pytest.fixture(autouse=True)
def _limiter_off() -> AsyncIterator[None]:
    limiter.enabled = False
    yield
    limiter.enabled = True
    limiter.reset()


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
def app(db: AsyncSession) -> FastAPI:
    application = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db

    application.dependency_overrides[get_db] = _override

    @asynccontextmanager
    async def _shared() -> AsyncIterator[AsyncSession]:  # streaming/background code reuses the rolled-back test session
        yield db

    application.dependency_overrides[get_session_factory] = lambda: _shared
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- LLM test double (reused by later parts) ----------


def tool_call(name: str, id: str | None = None, **arguments: Any) -> ToolCall:
    return ToolCall(id=id or f"call_{name}", name=name, arguments=arguments)


def tool_response(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls), usage={})


class FakeProvider(LLMProvider):
    """Scripted LLMProvider. Every call pops the next scripted item; exception items are raised.

    texts: strings for stream_chat (streamed word by word).
    jsons: dicts for chat_json.
    tool_responses: LLMResponse objects (see tool_response) or plain strings for chat_with_tools.
    `calls` records every invocation (method, system, messages, ...). An empty script raises AssertionError.
    """

    def __init__(self, *, texts: Sequence[Any] = (), jsons: Sequence[Any] = (), tool_responses: Sequence[Any] = ()) -> None:
        self._texts, self._jsons, self._tools = deque(texts), deque(jsons), deque(tool_responses)
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _pop(queue: deque[Any], kind: str) -> Any:
        if not queue:
            raise AssertionError(f"FakeProvider: no scripted {kind} left")
        item = queue.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def _record(self, method: str, system: str, messages: Sequence[ChatMessage], **extra: Any) -> None:
        self.calls.append({"method": method, "system": system, "messages": list(messages), **extra})

    async def stream_chat(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        self._record("stream_chat", system, messages)
        for chunk in re.findall(r"\S+\s*", self._pop(self._texts, "text")):
            yield chunk

    async def chat_json(
        self, system: str, messages: Sequence[ChatMessage], schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._record("chat_json", system, messages, schema=schema)
        return copy.deepcopy(self._pop(self._jsons, "json"))

    async def chat_with_tools(
        self, system: str, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        self._record("chat_with_tools", system, messages, tools=list(tools))
        item = self._pop(self._tools, "tool response")
        return LLMResponse(text=item) if isinstance(item, str) else item


@pytest.fixture
def use_fake_llm() -> Iterator[Callable[..., FakeProvider]]:
    """`provider = use_fake_llm(texts=[...], jsons=[...], tool_responses=[...])` makes get_provider() return it."""

    def _install(**script: Any) -> FakeProvider:
        provider = FakeProvider(**script)
        set_provider_override(provider)
        return provider

    yield _install
    set_provider_override(None)
