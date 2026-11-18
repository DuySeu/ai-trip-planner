"""Exception handlers: every error leaves the API in the envelope, never with raw exception text."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.envelope import error_response
from api.middleware import REQUEST_ID_HEADER
from core.exceptions import Conflict, LimitExceeded, NotFound, QuotaExhausted
from core.logger import log_context

logger = logging.getLogger(__name__)

MAX_VALIDATION_ISSUES = 5
HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    429: "rate_limited",
}
INTERNAL_MESSAGE = "Something went wrong on our side. Please try again."


# NotFound -> 404
async def handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, "not_found", str(exc) or "Not found")


# Conflict and PlanConflict -> 409
async def handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        409, "conflict", str(exc) or "The request conflicts with the current state"
    )


# LimitExceeded -> 429
async def handle_limit(request: Request, exc: Exception) -> JSONResponse:
    return error_response(429, "rate_limited", str(exc) or "Too many requests")


# QuotaExhausted -> 429 with the time the provider's quota resets
async def handle_quota(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, QuotaExhausted)
    message = (
        f"The free AI limit is used up for now. Try again after {exc.blocked_until.isoformat()}."
    )
    return error_response(429, "quota_exhausted", message)


# Request validation -> 422 listing where each problem is, without echoing the input
async def handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    issues = [
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors()[:MAX_VALIDATION_ISSUES]
    ]
    return error_response(422, "invalid_request", "; ".join(issues) or "Invalid request")


# Framework HTTP errors (unknown route, wrong method, body too large) -> the envelope
async def handle_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, str(exc.detail), exc.headers)


# Anything else -> 500 with a fixed message; the exception goes to the log with the request id
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    with log_context(request_id=request_id):
        logger.error(
            "unhandled error on %s %s (request %s)",
            request.method,
            request.url.path,
            request_id,
            exc_info=exc,
        )
    return error_response(500, "internal_error", INTERNAL_MESSAGE, {REQUEST_ID_HEADER: request_id})


# Register every handler on the app
def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFound, handle_not_found)
    app.add_exception_handler(Conflict, handle_conflict)
    app.add_exception_handler(LimitExceeded, handle_limit)
    app.add_exception_handler(QuotaExhausted, handle_quota)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http)
    app.add_exception_handler(Exception, handle_unexpected)
