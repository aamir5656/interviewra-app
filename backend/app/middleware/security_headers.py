from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h.setdefault("X-Content-Type-Options", "nosniff")
                h.setdefault("X-Frame-Options", "DENY")
                h.setdefault("Referrer-Policy", "no-referrer")
                h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                if not path.startswith(_DOC_PATHS):
                    h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                if path.startswith("/api/"):
                    h.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
            await send(message)

        await self.app(scope, receive, send_wrapper)
