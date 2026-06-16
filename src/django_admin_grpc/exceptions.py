"""
Exception hierarchy for django-admin-grpc.

Maps gRPC status codes to typed Python exceptions.
"""

from __future__ import annotations

from typing import Any

import grpc


class GrpcAdminError(Exception):
    """Base exception for all django-admin-grpc errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        grpc_code: grpc.StatusCode | None = None,
        details: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.grpc_code = grpc_code
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"(code={self.code})")
        if self.grpc_code:
            parts.append(f"(grpc_code={self.grpc_code.name})")
        return " ".join(parts)


class GrpcNotFoundError(GrpcAdminError):
    """The requested resource was not found on the gRPC service."""

    pass


class GrpcPermissionDeniedError(GrpcAdminError):
    """The caller does not have permission to perform this action."""

    pass


class GrpcInvalidArgumentError(GrpcAdminError):
    """One or more arguments are invalid."""

    pass


class GrpcUnavailableError(GrpcAdminError):
    """The gRPC service is currently unavailable."""

    pass


class GrpcDeadlineExceededError(GrpcAdminError):
    """The gRPC call deadline was exceeded before completion."""

    pass


class GrpcAlreadyExistsError(GrpcAdminError):
    """The requested resource already exists on the gRPC service."""

    pass


class GrpcResourceExhaustedError(GrpcAdminError):
    """The gRPC service has exhausted a resource (quota, rate limit, etc.)."""

    pass


class GrpcFailedPreconditionError(GrpcAdminError):
    """The request failed because a precondition was not met."""

    pass


class GrpcAbortedError(GrpcAdminError):
    """The gRPC operation was aborted, usually retryable."""

    pass


class GrpcCancelledError(GrpcAdminError):
    """The gRPC operation was cancelled by the client or server."""

    pass


class GrpcBatchPartialError(GrpcAdminError):
    """
    Raised when a bulk gRPC operation finishes with a mix of successes and failures.

    Attributes:
        succeeded: Primary keys (or input items) that were processed successfully.
        failed: Mapping of ``{pk: error}`` (or list of items) that failed.
        operation: Name of the bulk operation (``"bulk_create"``, ``"bulk_update"``,
            ``"bulk_delete"``) so callers can react without sniffing the type.
    """

    def __init__(
        self,
        message: str,
        *,
        succeeded: list[Any] | None = None,
        failed: dict[Any, Exception] | list[Any] | None = None,
        operation: str | None = None,
        code: str | None = None,
        grpc_code: grpc.StatusCode | None = None,
        details: str | None = None,
    ):
        super().__init__(
            message,
            code=code or "BATCH_PARTIAL",
            grpc_code=grpc_code,
            details=details,
        )
        self.succeeded: list[Any] = list(succeeded or [])
        self.failed: dict[Any, Exception] | list[Any] = failed if failed is not None else {}
        self.operation: str | None = operation

    def __str__(self) -> str:
        parts = [self.message]
        if self.operation:
            parts.append(f"(operation={self.operation})")
        parts.append(f"(succeeded={len(self.succeeded)} failed={len(self.failed)})")
        if self.code:
            parts.append(f"(code={self.code})")
        if self.grpc_code:
            parts.append(f"(grpc_code={self.grpc_code.name})")
        return " ".join(parts)


def map_grpc_error(exc: grpc.RpcError) -> GrpcAdminError:
    """
    Map a grpc.RpcError to the appropriate GrpcAdminError subclass.

    Args:
        exc: The gRPC error to map.

    Returns:
        A typed GrpcAdminError instance.
    """
    code = exc.code() if hasattr(exc, "code") else None
    details = exc.details() if hasattr(exc, "details") else str(exc)
    message = details or "gRPC error occurred"

    mapping: dict[grpc.StatusCode, type[GrpcAdminError]] = {
        grpc.StatusCode.NOT_FOUND: GrpcNotFoundError,
        grpc.StatusCode.PERMISSION_DENIED: GrpcPermissionDeniedError,
        grpc.StatusCode.UNAUTHENTICATED: GrpcPermissionDeniedError,
        grpc.StatusCode.INVALID_ARGUMENT: GrpcInvalidArgumentError,
        grpc.StatusCode.UNAVAILABLE: GrpcUnavailableError,
        grpc.StatusCode.DEADLINE_EXCEEDED: GrpcDeadlineExceededError,
        grpc.StatusCode.ALREADY_EXISTS: GrpcAlreadyExistsError,
        grpc.StatusCode.RESOURCE_EXHAUSTED: GrpcResourceExhaustedError,
        grpc.StatusCode.FAILED_PRECONDITION: GrpcFailedPreconditionError,
        grpc.StatusCode.ABORTED: GrpcAbortedError,
        grpc.StatusCode.CANCELLED: GrpcCancelledError,
    }

    exc_class = mapping.get(code, GrpcAdminError)
    return exc_class(
        message,
        code=code.name if code else None,
        grpc_code=code,
        details=details,
    )


def get_grpc_error_message(exc: GrpcAdminError) -> tuple[int, str]:
    """
    Return a Django messages level and a human-readable message for *exc*.

    Args:
        exc: A typed gRPC admin exception.

    Returns:
        A tuple of (level, message) suitable for ``messages.add_message``.
    """
    from django.contrib import messages

    if isinstance(exc, GrpcAlreadyExistsError):
        return messages.ERROR, "Record already exists"
    if isinstance(exc, GrpcResourceExhaustedError):
        return messages.WARNING, "Service is busy, try again later"
    if isinstance(exc, GrpcFailedPreconditionError):
        return messages.ERROR, exc.message or "Request failed precondition"
    if isinstance(exc, GrpcAbortedError):
        return messages.WARNING, "Request aborted, please retry"
    if isinstance(exc, GrpcCancelledError):
        return messages.WARNING, "Request was cancelled"
    if isinstance(exc, GrpcNotFoundError):
        return messages.ERROR, exc.message or "Record not found"
    if isinstance(exc, GrpcPermissionDeniedError):
        return messages.ERROR, exc.message or "Permission denied"
    if isinstance(exc, GrpcInvalidArgumentError):
        return messages.ERROR, exc.message or "Validation failed"
    if isinstance(exc, GrpcUnavailableError):
        return messages.ERROR, exc.message or "Service unavailable"
    if isinstance(exc, GrpcDeadlineExceededError):
        return messages.ERROR, exc.message or "Request timed out"
    return messages.ERROR, exc.message or "An error occurred"
