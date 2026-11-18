"""Request id and request body size cap, as plain ASGI middleware (they must see raw messages)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.envelope import error_response
from core.logger import log_context

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a client's id only if it is short and plain; anything else could forge log lines
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
MAX_BODY_BYTES = 64 * 1024


# The request body is larger than the cap
class PayloadTooLarge(HTTPException):
    # A 413 that the HTTP exception handler renders into the envelope
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body is too large")


# Give every request an id (X-Request-ID in, or a new one), echo it, and add it to every log line
class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Take a safe incoming id or make one, and share it through the request state
        sent = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode("latin-1")
        request_id = sent if SAFE_REQUEST_ID.fullmatch(sent) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        # Put the id on the response start
        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode()),
                ]
            await send(message)

        with log_context(request_id=request_id):
            await self.app(scope, receive, send_with_id)


# Reject bodies over the cap: by Content-Length when it is honest, by counting streamed bytes always
class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Refuse at once when the declared length is over the cap; ignore a malformed one
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            response = error_response(413, "payload_too_large", "Request body is too large")
            await response(scope, receive, send)
            return

        # Count what is really read; a missing or lying Content-Length cannot get past this
        received = 0

        async def counted_receive() -> Message:
            nonlocal received
            message: dict[str, Any] = dict(await receive())
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise PayloadTooLarge()
            return message

        await self.app(scope, counted_receive, send)
