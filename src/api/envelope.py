"""The response shape every endpoint returns, success or error."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi.responses import JSONResponse
from pydantic import BaseModel


# Why a request failed, in a form a client can switch on
class ErrorBody(BaseModel):
    code: str
    message: str


# Paging facts for list endpoints
class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


# The response shape every endpoint returns; the status code and `success` always agree
class ApiResponse[T](BaseModel):
    success: bool
    data: T | None = None
    error: ErrorBody | None = None
    meta: PageMeta | None = None


# A failed response in the same envelope as a successful one
def error_response(
    status_code: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = ApiResponse[None](success=False, error=ErrorBody(code=code, message=message))
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=dict(headers or {})
    )
