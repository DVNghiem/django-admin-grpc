"""
Exception hierarchy for django-grpc-admin.

Maps gRPC status codes to typed Python exceptions.
"""

import grpc


class GrpcAdminError(Exception):
    """Base exception for all django-grpc-admin errors."""

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
    }

    exc_class = mapping.get(code, GrpcAdminError)
    return exc_class(
        message,
        code=code.name if code else None,
        grpc_code=code,
        details=details,
    )
