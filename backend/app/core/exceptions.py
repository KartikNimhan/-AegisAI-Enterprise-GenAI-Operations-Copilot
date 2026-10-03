"""Application exceptions and a consistent JSON error envelope."""

from typing import Any

import structlog
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.documents.exceptions import DocumentValidationError
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for application-raised errors that map to a JSON response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "internal_error",
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Service temporarily unavailable") -> None:
        super().__init__(
            message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="service_unavailable",
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, code="not_found")


def _error_payload(request: Request, *, code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, code=exc.code, message=exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_payload(request, code="validation_error", message=str(exc.errors())),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, code="http_error", message=detail),
        )

    @app.exception_handler(DocumentValidationError)
    async def handle_document_validation_error(
        request: Request, exc: DocumentValidationError
    ) -> JSONResponse:
        logger.warning("document_validation_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_payload(request, code="document_validation_error", message=str(exc)),
        )

    @app.exception_handler(LLMRateLimitError)
    async def handle_llm_rate_limit_error(request: Request, exc: LLMRateLimitError) -> JSONResponse:
        logger.warning("llm_rate_limited", provider=exc.provider, request_id=exc.request_id)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=_error_payload(request, code="llm_rate_limited", message=str(exc)),
        )

    @app.exception_handler(LLMTimeoutError)
    async def handle_llm_timeout_error(request: Request, exc: LLMTimeoutError) -> JSONResponse:
        logger.warning("llm_timeout", provider=exc.provider, request_id=exc.request_id)
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=_error_payload(request, code="llm_timeout", message=str(exc)),
        )

    @app.exception_handler(LLMAuthenticationError)
    async def handle_llm_authentication_error(
        request: Request, exc: LLMAuthenticationError
    ) -> JSONResponse:
        # Never reflect provider auth details back to the API consumer.
        logger.error("llm_authentication_error", provider=exc.provider)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_payload(
                request, code="llm_unavailable", message="The LLM provider is not available"
            ),
        )

    @app.exception_handler(LLMInvalidRequestError)
    async def handle_llm_invalid_request_error(
        request: Request, exc: LLMInvalidRequestError
    ) -> JSONResponse:
        logger.warning("llm_invalid_request", provider=exc.provider, request_id=exc.request_id)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_payload(request, code="llm_invalid_request", message=str(exc)),
        )

    @app.exception_handler(LLMProviderUnavailableError)
    async def handle_llm_provider_unavailable_error(
        request: Request, exc: LLMProviderUnavailableError
    ) -> JSONResponse:
        logger.warning("llm_provider_unavailable", provider=exc.provider, request_id=exc.request_id)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_payload(request, code="llm_unavailable", message=str(exc)),
        )

    @app.exception_handler(LLMError)
    async def handle_llm_error(request: Request, exc: LLMError) -> JSONResponse:
        # Catch-all for unmapped LLM errors (e.g. LLMProviderError). Never
        # leak the raw provider exception to the caller.
        logger.error("llm_unexpected_error", provider=exc.provider, request_id=exc.request_id)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=_error_payload(
                request, code="llm_provider_error", message="The LLM provider returned an error"
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                request, code="internal_error", message="An unexpected error occurred"
            ),
        )
