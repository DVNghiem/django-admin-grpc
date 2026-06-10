"""
Tests for django_admin_grpc.interceptors module.
"""
from unittest.mock import Mock, patch

import grpc
import pytest

from django_admin_grpc.interceptors import TraceClientInterceptor, _default_provider


class TestDefaultProvider:
    def test_returns_empty_dict(self):
        assert _default_provider() == {}


class TestTraceClientInterceptor:
    def test_init_default_provider(self):
        interceptor = TraceClientInterceptor()
        assert interceptor._provider is _default_provider

    def test_init_custom_provider(self):
        provider = lambda: {"x-trace-id": "123"}  # noqa: E731
        interceptor = TraceClientInterceptor(trace_context_provider=provider)
        assert interceptor._provider is provider

    def test_intercept_unary_unary_success(self):
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "abc"}
        )

        mock_response = Mock()
        continuation = Mock(return_value=mock_response)

        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/method"
        call_details.timeout = 30
        call_details.credentials = None
        call_details.metadata = [("existing", "header")]
        call_details.wait_for_ready = None
        call_details.compression = None

        request = Mock()

        with patch(
            "django_admin_grpc.interceptors.time.monotonic", side_effect=[0.0, 0.123]
        ):
            result = interceptor.intercept_unary_unary(
                continuation, call_details, request
            )

        assert result is mock_response
        continuation.assert_called_once()
        passed_details = continuation.call_args[0][0]
        assert passed_details.method == "/service/method"
        assert ("x-request-id", "abc") in passed_details.metadata
        assert ("existing", "header") in passed_details.metadata

    def test_intercept_unary_unary_no_trace_context(self):
        interceptor = TraceClientInterceptor(trace_context_provider=lambda: {})

        mock_response = Mock()
        continuation = Mock(return_value=mock_response)

        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/method"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = None
        call_details.wait_for_ready = None
        call_details.compression = None

        result = interceptor.intercept_unary_unary(
            continuation, call_details, Mock()
        )
        assert result is mock_response
        passed_details = continuation.call_args[0][0]
        assert passed_details.metadata == []

    def test_intercept_unary_unary_filters_none_values(self):
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "abc", "x-null": None}
        )

        continuation = Mock(return_value=Mock())
        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/method"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = []
        call_details.wait_for_ready = None
        call_details.compression = None

        interceptor.intercept_unary_unary(continuation, call_details, Mock())
        passed_details = continuation.call_args[0][0]
        metadata_dict = dict(passed_details.metadata)
        assert "x-request-id" in metadata_dict
        assert "x-null" not in metadata_dict

    def test_intercept_unary_unary_rpc_error(self):
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "abc"}
        )

        class MockRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.UNAVAILABLE
            def details(self):
                return "service unavailable"

        mock_exc = MockRpcError()
        continuation = Mock(side_effect=mock_exc)

        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/method"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = []
        call_details.wait_for_ready = None
        call_details.compression = None

        with patch(
            "django_admin_grpc.interceptors.time.monotonic", side_effect=[0.0, 0.5]
        ), pytest.raises(grpc.RpcError):
            interceptor.intercept_unary_unary(
                continuation, call_details, Mock()
            )

        continuation.assert_called_once()

    def test_intercept_unary_unary_preserves_optional_attributes(self):
        interceptor = TraceClientInterceptor()

        continuation = Mock(return_value=Mock())
        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/method"
        call_details.timeout = 60
        call_details.credentials = Mock()
        call_details.wait_for_ready = True
        call_details.compression = grpc.Compression.Gzip
        call_details.metadata = []

        interceptor.intercept_unary_unary(continuation, call_details, Mock())
        passed_details = continuation.call_args[0][0]
        assert passed_details.timeout == 60
        assert passed_details.credentials is call_details.credentials
        assert passed_details.wait_for_ready is True
        assert passed_details.compression is grpc.Compression.Gzip

    def test_intercept_unary_stream_injects_trace_headers(self):
        """Regression: streaming calls must also receive trace headers."""
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "stream"}
        )
        continuation = Mock(return_value=iter([Mock()]))
        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/stream"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = []
        call_details.wait_for_ready = None
        call_details.compression = None

        result = interceptor.intercept_unary_stream(
            continuation, call_details, Mock()
        )
        assert result is not None
        passed_details = continuation.call_args[0][0]
        assert ("x-request-id", "stream") in passed_details.metadata

    def test_intercept_stream_unary_injects_trace_headers(self):
        """Regression: stream-unary calls must also receive trace headers."""
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "stream"}
        )
        continuation = Mock(return_value=Mock())
        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/stream"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = []
        call_details.wait_for_ready = None
        call_details.compression = None

        result = interceptor.intercept_stream_unary(
            continuation, call_details, iter([Mock()])
        )
        assert result is not None
        passed_details = continuation.call_args[0][0]
        assert ("x-request-id", "stream") in passed_details.metadata

    def test_intercept_stream_stream_injects_trace_headers(self):
        """Regression: stream-stream calls must also receive trace headers."""
        interceptor = TraceClientInterceptor(
            trace_context_provider=lambda: {"x-request-id": "stream"}
        )
        continuation = Mock(return_value=iter([Mock()]))
        call_details = Mock(spec=grpc.ClientCallDetails)
        call_details.method = "/service/stream"
        call_details.timeout = None
        call_details.credentials = None
        call_details.metadata = []
        call_details.wait_for_ready = None
        call_details.compression = None

        result = interceptor.intercept_stream_stream(
            continuation, call_details, iter([Mock()])
        )
        assert result is not None
        passed_details = continuation.call_args[0][0]
        assert ("x-request-id", "stream") in passed_details.metadata
