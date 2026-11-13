import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from app.services.llm.base import LLMProvider
from app.services.llm.retry import (
    MAX_ATTEMPTS, FatalError, RetryableError, backoff_delay, call_with_retries, unavailable,
)

logger = logging.getLogger("app.llm")
_RETRY_STATUS = {408, 425, 429}


class HTTPProvider(LLMProvider):
    """Shared httpx plumbing: per-call client, timeout, retry/backoff, SSE streaming."""

    name = "http"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self._sleep = sleep
        self.max_attempts = max_attempts

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _classify(self, status: int, body: str, headers: httpx.Headers) -> RetryableError | FatalError:
        if status in _RETRY_STATUS or status >= 500:
            retry_after: float | None = None
            try:
                retry_after = float(headers.get("retry-after", ""))
            except ValueError:
                pass
            return RetryableError(f"HTTP {status}", retry_after)
        return FatalError(f"HTTP {status}: {body[:300]}")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        async def op() -> dict[str, Any]:
            try:
                async with self._client() as client:
                    resp = await client.post(url, headers=self._headers(), json=payload)
            except httpx.TimeoutException:
                raise RetryableError("timeout") from None
            except httpx.TransportError as exc:
                raise RetryableError(f"transport:{type(exc).__name__}") from None
            if resp.status_code >= 400:
                raise self._classify(resp.status_code, resp.text, resp.headers)
            try:
                data = resp.json()
            except ValueError:
                raise RetryableError("invalid_response_body") from None
            if not isinstance(data, dict):
                raise RetryableError("unexpected_response_shape")
            return data

        return await call_with_retries(op, provider=self.name, max_attempts=self.max_attempts, sleep=self._sleep)

    async def _stream_events(self, url: str, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed SSE `data:` events. Retries only while nothing has been yielded yet."""
        for attempt in range(1, self.max_attempts + 1):
            yielded = False
            try:
                async with self._client() as client:
                    async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                        if resp.status_code >= 400:
                            body = (await resp.aread()).decode("utf-8", "replace")
                            raise self._classify(resp.status_code, body, resp.headers)
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            if not data:
                                continue
                            try:
                                event = json.loads(data)
                            except ValueError:
                                continue
                            yielded = True
                            yield event
                return
            except httpx.TimeoutException:
                err: RetryableError = RetryableError("timeout")
            except httpx.TransportError as exc:
                err = RetryableError(f"transport:{type(exc).__name__}")
            except RetryableError as exc:
                err = exc
            except FatalError as exc:
                logger.error("llm_fatal_error", extra={"provider": self.name, "reason": exc.reason})
                raise unavailable() from None
            logger.warning("llm_retryable_error", extra={"provider": self.name, "attempt": attempt, "reason": err.reason})
            if yielded or attempt == self.max_attempts:  # tokens already delivered: cannot transparently retry
                break
            await self._sleep(backoff_delay(attempt, err.retry_after))
        raise unavailable()
