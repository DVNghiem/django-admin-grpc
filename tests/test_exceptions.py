"""
Tests for django_admin_grpc.exceptions module.
"""
from unittest.mock import Mock

import grpc

from django_admin_grpc.exceptions import (
    GrpcAbortedError,
    GrpcAdminError,
    GrpcAlreadyExistsError,
    GrpcCancelledError,
    GrpcDeadlineExceededError,
    GrpcFailedPreconditionError,
    GrpcInvalidArgumentError,
    GrpcNotFoundError,
    GrpcPermissionDeniedError,
    GrpcResourceExhaustedError,
    GrpcUnavailableError,
    get_grpc_error_message,
    map_grpc_error,
)


class MockRpcError(grpc.RpcError):
    def __init__(self, code, details="error detail"):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


class TestGrpcAdminError:
    def test_basic_message(self):
        exc = GrpcAdminError("Something went wrong")
        assert str(exc) == "Something went wrong"
        assert exc.message == "Something went wrong"
        assert exc.code is None
        assert exc.grpc_code is None
        assert exc.details is None

    def test_with_code(self):
        exc = GrpcAdminError("Not found", code="NOT_FOUND", grpc_code=grpc.StatusCode.NOT_FOUND)
        assert "(code=NOT_FOUND)" in str(exc)
        assert "(grpc_code=NOT_FOUND)" in str(exc)

    def test_subclasses(self):
        assert issubclass(GrpcNotFoundError, GrpcAdminError)
        assert issubclass(GrpcPermissionDeniedError, GrpcAdminError)
        assert issubclass(GrpcInvalidArgumentError, GrpcAdminError)
        assert issubclass(GrpcUnavailableError, GrpcAdminError)
        assert issubclass(GrpcDeadlineExceededError, GrpcAdminError)
        assert issubclass(GrpcAlreadyExistsError, GrpcAdminError)
        assert issubclass(GrpcResourceExhaustedError, GrpcAdminError)
        assert issubclass(GrpcFailedPreconditionError, GrpcAdminError)
        assert issubclass(GrpcAbortedError, GrpcAdminError)
        assert issubclass(GrpcCancelledError, GrpcAdminError)


class TestMapGrpcError:
    def _make_rpc_error(self, code, details="error detail"):
        return MockRpcError(code, details)

    def test_not_found(self):
        exc = self._make_rpc_error(grpc.StatusCode.NOT_FOUND, "item missing")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcNotFoundError)
        assert result.message == "item missing"
        assert result.code == "NOT_FOUND"
        assert result.grpc_code == grpc.StatusCode.NOT_FOUND

    def test_permission_denied(self):
        exc = self._make_rpc_error(grpc.StatusCode.PERMISSION_DENIED, "access denied")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcPermissionDeniedError)
        assert "access denied" in str(result)

    def test_unauthenticated(self):
        exc = self._make_rpc_error(grpc.StatusCode.UNAUTHENTICATED, "not authenticated")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcPermissionDeniedError)
        assert result.code == "UNAUTHENTICATED"

    def test_invalid_argument(self):
        exc = self._make_rpc_error(grpc.StatusCode.INVALID_ARGUMENT, "bad input")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcInvalidArgumentError)
        assert result.code == "INVALID_ARGUMENT"

    def test_unavailable(self):
        exc = self._make_rpc_error(grpc.StatusCode.UNAVAILABLE, "service down")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcUnavailableError)
        assert result.code == "UNAVAILABLE"

    def test_deadline_exceeded(self):
        exc = self._make_rpc_error(grpc.StatusCode.DEADLINE_EXCEEDED, "timeout")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcDeadlineExceededError)
        assert result.code == "DEADLINE_EXCEEDED"

    def test_already_exists(self):
        exc = self._make_rpc_error(grpc.StatusCode.ALREADY_EXISTS, "exists")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcAlreadyExistsError)
        assert result.code == "ALREADY_EXISTS"

    def test_resource_exhausted(self):
        exc = self._make_rpc_error(grpc.StatusCode.RESOURCE_EXHAUSTED, "busy")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcResourceExhaustedError)
        assert result.code == "RESOURCE_EXHAUSTED"

    def test_failed_precondition(self):
        exc = self._make_rpc_error(grpc.StatusCode.FAILED_PRECONDITION, "bad state")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcFailedPreconditionError)
        assert result.code == "FAILED_PRECONDITION"

    def test_aborted(self):
        exc = self._make_rpc_error(grpc.StatusCode.ABORTED, "aborted")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcAbortedError)
        assert result.code == "ABORTED"

    def test_cancelled(self):
        exc = self._make_rpc_error(grpc.StatusCode.CANCELLED, "cancelled")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcCancelledError)
        assert result.code == "CANCELLED"

    def test_unknown_code(self):
        exc = self._make_rpc_error(grpc.StatusCode.UNKNOWN, "unknown error")
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcAdminError)
        assert not isinstance(result, GrpcNotFoundError)
        assert result.code == "UNKNOWN"

    def test_no_code_method(self):
        exc = Mock()
        # No code() method
        del exc.code
        result = map_grpc_error(exc)
        assert isinstance(result, GrpcAdminError)
        assert result.code is None

    def test_no_details_method(self):
        class NoDetailsError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.INTERNAL
            # No details() method

        exc = NoDetailsError()
        result = map_grpc_error(exc)
        assert result.details == str(exc)
        # When details is empty, message falls back to default
        assert result.message == "gRPC error occurred"

    def test_fallback_message(self):
        class PlainError(Exception):
            pass

        exc = PlainError()
        result = map_grpc_error(exc)
        assert result.message == "gRPC error occurred"


class TestGetGrpcErrorMessage:
    def test_already_exists(self):
        exc = GrpcAlreadyExistsError("exists")
        level, message = get_grpc_error_message(exc)
        assert level == 40  # messages.ERROR
        assert message == "Record already exists"

    def test_resource_exhausted(self):
        exc = GrpcResourceExhaustedError("busy")
        level, message = get_grpc_error_message(exc)
        assert level == 30  # messages.WARNING
        assert message == "Service is busy, try again later"

    def test_failed_precondition(self):
        exc = GrpcFailedPreconditionError("bad state")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "bad state"

    def test_aborted(self):
        exc = GrpcAbortedError("aborted")
        level, message = get_grpc_error_message(exc)
        assert level == 30
        assert message == "Request aborted, please retry"

    def test_cancelled(self):
        exc = GrpcCancelledError("cancelled")
        level, message = get_grpc_error_message(exc)
        assert level == 30
        assert message == "Request was cancelled"

    def test_not_found(self):
        exc = GrpcNotFoundError("missing")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "missing"

    def test_permission_denied(self):
        exc = GrpcPermissionDeniedError("access denied")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "access denied"

    def test_invalid_argument(self):
        exc = GrpcInvalidArgumentError("bad input")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "bad input"

    def test_unavailable(self):
        exc = GrpcUnavailableError("service down")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "service down"

    def test_deadline_exceeded(self):
        exc = GrpcDeadlineExceededError("timeout")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "timeout"

    def test_default(self):
        exc = GrpcAdminError("boom")
        level, message = get_grpc_error_message(exc)
        assert level == 40
        assert message == "boom"
