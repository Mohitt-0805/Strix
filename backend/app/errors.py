"""Uniform JSON error types and FastAPI exception handlers."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    501: "NOT_AVAILABLE",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    """Application error rendered in the standard {detail, code} shape."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def error_payload(detail: str, code: str) -> dict[str, str]:
    """Build the canonical error response body."""
    return {"detail": detail, "code": code}


def code_for_status(status_code: int) -> str:
    """Map an HTTP status code to an UPPER_SNAKE error code."""
    return _STATUS_CODES.get(status_code, f"HTTP_{status_code}")


def register_error_handlers(app: FastAPI) -> None:
    """Attach uniform JSON error handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.detail, exc.code),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(str(exc.detail), code_for_status(exc.status_code)),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(segment) for segment in err.get("loc", []))
            msg = err.get("msg", "Invalid value")
            parts.append(f"{loc}: {msg}" if loc else msg)
        detail = "; ".join(parts) or "Validation error."
        return JSONResponse(
            status_code=422,
            content=error_payload(detail, "VALIDATION_ERROR"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(
        _request: Request, _exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception while serving request")
        return JSONResponse(
            status_code=500,
            content=error_payload("Internal server error.", "INTERNAL_ERROR"),
        )
