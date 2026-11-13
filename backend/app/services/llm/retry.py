import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.errors import AppError

T = TypeVar("T")
logger = logging.getLogger("app.llm")

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 8.0
UNAVAILABLE_MESSAGE = "The AI service is temporarily unavailable. Please try again in a moment."


class RetryableError(Exception):
    """429 / 5xx / timeout / network error: worth another attempt."""

    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class FatalError(Exception):
    """Non-retryable provider error (bad key, bad request...)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def unavailable() -> AppError:
    return AppError("llm_unavailable", UNAVAILABLE_MESSAGE, 503)


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff (0.5s, 1s, 2s...) capped at MAX_DELAY_SECONDS; honours Retry-After; small jitter."""
    delay = retry_after if retry_after is not None else BASE_DELAY_SECONDS * 2 ** (attempt - 1)
    return min(delay, MAX_DELAY_SECONDS) + random.uniform(0, 0.1)


async def call_with_retries(
    op: Callable[[], Awaitable[T]],
    *,
    provider: str = "llm",
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return await op()
        except RetryableError as exc:
            logger.warning("llm_retryable_error", extra={"provider": provider, "attempt": attempt, "reason": exc.reason})
            if attempt == max_attempts:
                break
            await sleep(backoff_delay(attempt, exc.retry_after))
        except FatalError as exc:
            logger.error("llm_fatal_error", extra={"provider": provider, "reason": exc.reason})
            raise unavailable() from None
    raise unavailable()
