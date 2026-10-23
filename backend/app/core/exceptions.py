"""Application exceptions and a consistent JSON error envelope."""

from typing import Any

import structlog
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agents.exceptions import AgentTimeoutError
from app.core.middleware import SECURITY_HEADERS
from app.documents.exceptions import DocumentValidationError
from app.embeddings.exceptions import (
    DocumentNotReadyError,
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
)
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
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.headers = headers
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


# Authentication errors. The messages are deliberately generic: the specific
# reason (expired, wrong audience, unknown identity, ...) is logged server-side
# with the request id, never returned to the caller and never including the token.
class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(
            message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN, code="forbidden")


class AuthUnavailableError(AppError):
    def __init__(self, message: str = "Authentication is temporarily unavailable") -> None:
        super().__init__(
            message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, code="auth_unavailable"
        )


def _error_payload(
    request: Request, *, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


# A 422 must say what is wrong without repeating what was sent: Pydantic's raw errors include the
# rejected `input` (a 2 MB string comes back in full; a mistakenly pasted secret is echoed) and
# parser internals (`ctx`). Only where (`loc`), what (`msg`) and the error `type` are returned.
_MAX_VALIDATION_DETAILS = 20
_MAX_LOC_PART_CHARS = 64
_MAX_MSG_CHARS = 200


def _validation_details(errors: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in list(errors)[:_MAX_VALIDATION_DETAILS]:
        if not isinstance(error, dict):
            continue
        loc = [str(part)[:_MAX_LOC_PART_CHARS] for part in error.get("loc", ())]
        details.append(
            {
                "loc": loc,
                "msg": str(error.get("msg", "Invalid value"))[:_MAX_MSG_CHARS],
                "type": str(error.get("type", "value_error"))[:_MAX_LOC_PART_CHARS],
            }
        )
    return details


def _validation_message(details: list[dict[str, Any]]) -> str:
    parts = [f"{'.'.join(d['loc']) or 'request'}: {d['msg']}" for d in details]
    return "; ".join(parts) if parts else "The request is invalid"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, code=exc.code, message=exc.message),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = _validation_details(exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_payload(
                request,
                code="validation_error",
                message=_validation_message(details),
                details=details,
            ),
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

    @app.exception_handler(DocumentNotReadyError)
    async def handle_document_not_ready_error(
        request: Request, exc: DocumentNotReadyError
    ) -> JSONResponse:
        logger.warning("document_not_ready_for_embedding", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_payload(request, code="document_not_ready", message=str(exc)),
        )

    @app.exception_handler(EmbeddingDimensionMismatchError)
    async def handle_embedding_dimension_mismatch_error(
        request: Request, exc: EmbeddingDimensionMismatchError
    ) -> JSONResponse:
        logger.error("embedding_dimension_mismatch", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                request, code="embedding_dimension_mismatch", message="Embedding generation failed"
            ),
        )

    @app.exception_handler(EmbeddingProviderError)
    async def handle_embedding_provider_error(
        request: Request, exc: EmbeddingProviderError
    ) -> JSONResponse:
        # Never reflect raw provider/library exception details to the caller.
        logger.error("embedding_provider_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=_error_payload(
                request, code="embedding_provider_error", message="Embedding generation failed"
            ),
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

    @app.exception_handler(AgentTimeoutError)
    async def handle_agent_timeout_error(request: Request, exc: AgentTimeoutError) -> JSONResponse:
        logger.warning("agent_timeout", message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=_error_payload(request, code="agent_timeout", message=str(exc)),
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
        # The outermost ServerErrorMiddleware builds this response, outside CorrelationIdMiddleware,
        # so the header is set here or a 500 would be the one response without it.
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                request, code="internal_error", message="An unexpected error occurred"
            ),
            headers={**SECURITY_HEADERS, **({"X-Request-ID": request_id} if request_id else {})},
        )
