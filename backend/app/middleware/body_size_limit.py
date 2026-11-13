from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import AppError


class BodySizeLimitMiddleware:
    """Small limit for JSON bodies; larger limit only for the resume upload path."""

    def __init__(
        self,
        app: ASGIApp,
        json_limit_bytes: int = 64 * 1024,
        upload_limit_bytes: int = 5 * 1024 * 1024,
        upload_path: str = "/api/v1/resume",
    ) -> None:
        self.app = app
        self.json_limit = json_limit_bytes
        self.upload_limit = upload_limit_bytes
        self.upload_path = upload_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.upload_limit if scope["path"].rstrip("/") == self.upload_path else self.json_limit
        too_large = AppError("payload_too_large", "Request body too large", 413)

        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                declared = 0
            if declared > limit:
                rid = scope.get("state", {}).get("request_id", "unknown")
                resp = JSONResponse(
                    status_code=413,
                    content={"error": {"code": too_large.code, "message": too_large.message, "request_id": rid}},
                )
                await resp(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise too_large  # handled by AppError handler (chunked bodies)
            return message

        await self.app(scope, limited_receive, send)
