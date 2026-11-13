import math
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.errors import error_response

DEFAULT_LIMIT = "60/minute"   # every route without its own limit
AUTH_LIMIT = "10/minute"      # login / register
GUEST_CREATE_LIMIT = "20/hour"  # POST /auth/guest (stops guest-farming to dodge daily limits)

limiter = Limiter(key_func=get_remote_address, default_limits=[DEFAULT_LIMIT])


def _retry_after(request: Request) -> int:
    try:
        limit, args = request.state.view_rate_limit
        reset_at, _ = limiter.limiter.get_window_stats(limit, *args)
        return max(1, math.ceil(reset_at - time.time()))
    except Exception:
        return 60


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RateLimitExceeded)
    return error_response(
        request, "rate_limited", "Too many requests. Please slow down and try again shortly.", 429,
        {"Retry-After": str(_retry_after(request))},
    )
