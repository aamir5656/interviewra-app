import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.ratelimit import limiter, rate_limit_exceeded_handler
from app.database import engine
from app.middleware.body_size_limit import BodySizeLimitMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.timing_logging import TimingLoggingMiddleware
from app.routers import auth, dashboard, history, interview, memory, resume
from app.services.cleanup import cleanup_loop

API_PREFIX = "/api/v1"
JSON_BODY_LIMIT_BYTES = 64 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("startup", extra={"env": get_settings().ENV})
    cleanup_task: asyncio.Task[None] | None = None
    if get_settings().CLEANUP_INTERVAL_HOURS > 0:
        cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        if cleanup_task:
            cleanup_task.cancel()
        await engine.dispose()
        logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging("INFO")

    app = FastAPI(
        title="Interviewra API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    register_error_handlers(app)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # add_middleware: last added = outermost. Order outer->inner:
    # RequestID, Timing, SecurityHeaders, CORS, SlowAPI, BodySizeLimit
    app.add_middleware(
        BodySizeLimitMiddleware,
        json_limit_bytes=JSON_BODY_LIMIT_BYTES,
        upload_limit_bytes=settings.MAX_UPLOAD_MB * 1024 * 1024 + MULTIPART_OVERHEAD_BYTES,
        upload_path=f"{API_PREFIX}/resume",
    )
    app.add_middleware(SlowAPIASGIMiddleware)  # default per-IP limit; inside CORS so 429s carry CORS headers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,  # bearer token in header, no cookies
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(TimingLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # --- Routers (later parts): app.include_router(<module>.router, prefix=API_PREFIX) ---
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(interview.router, prefix=API_PREFIX)
    app.include_router(history.router, prefix=API_PREFIX)
    app.include_router(memory.router, prefix=API_PREFIX)
    app.include_router(resume.router, prefix=API_PREFIX)
    app.include_router(dashboard.router, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"])
    @limiter.exempt
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
