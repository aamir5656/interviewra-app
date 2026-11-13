import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

_HTTP_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 429: "rate_limited",
}


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = dict(headers) if headers else None


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def error_response(
    request: Request, code: str, message: str, status_code: int, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    rid = request_id_of(request)
    out = dict(headers or {})
    out["X-Request-ID"] = rid
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": rid}},
        headers=out,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc.code, exc.message, exc.status_code, exc.headers)


_FIELD_LABELS = {"role_name": "Role", "level": "Level", "interview_type": "Interview type",
                 "question_count": "Number of questions", "content": "Answer", "email": "Email", "password": "Password",
                 "title": "Title", "resume_id": "Resume"}


def _friendly(error: dict) -> str:
    """One readable sentence for a validation problem (no 'Value error,' and no raw field paths)."""
    msg = str(error.get("msg", "Invalid value"))
    field = next((str(p) for p in reversed(error.get("loc", ())) if isinstance(p, str) and p != "body"), "")
    if msg.startswith("Value error, "):
        return msg[len("Value error, "):]
    label = _FIELD_LABELS.get(field)
    return f"{label}: {msg[:1].lower() + msg[1:]}" if label else msg


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    parts = list(dict.fromkeys(_friendly(e) for e in exc.errors()[:5]))
    return error_response(request, "validation_error", " ".join(parts) or "Invalid request", 422)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(request, code, str(exc.detail), exc.status_code, exc.headers)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"request_id": request_id_of(request), "path": request.url.path, "method": request.method},
    )
    return error_response(request, "internal_error", "Internal server error", 500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
