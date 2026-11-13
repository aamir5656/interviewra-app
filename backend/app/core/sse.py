import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anyio
from fastapi.responses import StreamingResponse

from app.core.errors import AppError

logger = logging.getLogger("app.sse")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse_event(name: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent Event: `event: <name>\\ndata: <json>\\n\\n`."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def guarded_stream(
    events: AsyncIterator[str], on_abort: Callable[[], Awaitable[None]] | None = None
) -> AsyncIterator[str]:
    """Yield `events`; if it fails, send a final `error` event instead of a broken stream.

    `on_abort` runs (shielded from cancellation) when the stream fails or the client disconnects,
    so the caller can undo half-finished work.
    """
    try:
        async for chunk in events:
            yield chunk
    except AppError as exc:
        await _abort(on_abort)
        yield sse_event("error", {"code": exc.code, "message": exc.message})
    except Exception:  # noqa: BLE001 - never leak internals; the client gets a generic error event
        logger.exception("sse_stream_failed")
        await _abort(on_abort)
        yield sse_event("error", {"code": "internal_error", "message": "Something went wrong. Please try again."})
    except BaseException:  # client disconnected (CancelledError / GeneratorExit)
        await _abort(on_abort)
        raise


async def _abort(on_abort: Callable[[], Awaitable[None]] | None) -> None:
    if on_abort is None:
        return
    try:
        with anyio.CancelScope(shield=True):
            await on_abort()
    except Exception:  # noqa: BLE001
        logger.exception("sse_abort_cleanup_failed")


def sse_response(events: AsyncIterator[str], on_abort: Callable[[], Awaitable[None]] | None = None, **kwargs: Any) -> StreamingResponse:
    return StreamingResponse(guarded_stream(events, on_abort), media_type="text/event-stream", headers=SSE_HEADERS, **kwargs)
