"""
gRPC client interceptor that injects trace context into outgoing calls.

The trace context is provided by a configurable callable so the package
remains agnostic of any specific logging framework.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import grpc

logger = logging.getLogger(__name__)

TraceContextProvider = Callable[[], dict[str, str]]


def _default_provider() -> dict[str, str]:
    """No-op provider that returns an empty mapping."""
    return {}


class _MutableCallDetails(grpc.ClientCallDetails):
    """Mutable wrapper so we can inject metadata after creation."""

    pass


class TraceClientInterceptor(grpc.UnaryUnaryClientInterceptor):
    """
    Injects trace headers (e.g. *x-request-id*, *x-trace-id*) into every
    outgoing gRPC call and emits structured latency logs.

    Args:
        trace_context_provider: A callable returning ``dict[str, str]`` of
            header name → header value. ``None`` values are filtered out.
    """

    def __init__(
        self,
        trace_context_provider: TraceContextProvider | None = None,
    ):
        self._provider = trace_context_provider or _default_provider

    def intercept_unary_unary(
        self,
        continuation: Callable,
        client_call_details: grpc.ClientCallDetails,
        request: Any,
    ) -> Any:
        ctx = self._provider()

        trace_meta = [
            (k, v)
            for k, v in ctx.items()
            if v is not None
        ]

        new_details = _MutableCallDetails()
        new_details.method = client_call_details.method
        new_details.timeout = getattr(client_call_details, "timeout", None)
        new_details.credentials = getattr(client_call_details, "credentials", None)
        new_details.wait_for_ready = getattr(
            client_call_details, "wait_for_ready", None
        )
        new_details.compression = getattr(
            client_call_details, "compression", None
        )
        new_details.metadata = list(client_call_details.metadata or []) + trace_meta

        method = client_call_details.method
        logger.debug("grpc.call.start  method=%s", method)

        start = time.monotonic()
        try:
            response = continuation(new_details, request)
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.info(
                "grpc.call.success  method=%s  status_code=OK  latency_ms=%s",
                method,
                latency_ms,
            )
            return response
        except grpc.RpcError as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "grpc.call.failure  method=%s  status_code=%s  latency_ms=%s  details=%s",
                method,
                exc.code().name if hasattr(exc, "code") else "UNKNOWN",
                latency_ms,
                exc.details() if hasattr(exc, "details") else str(exc),
            )
            raise
