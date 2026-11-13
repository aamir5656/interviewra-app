import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        rid = incoming if _VALID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = rid
            await send(message)

        await self.app(scope, receive, send_wrapper)
