"""
Built-in gRPC context/metadata providers.

Providers are callables that accept the current Django ``HttpRequest`` and
return a dict of metadata key/value pairs to inject into outgoing gRPC calls.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def _django_setting(name: str, default: Any) -> Any:
    """Return a top-level Django setting or its default."""
    return getattr(settings, name, default)


class TenantContextProvider:
    """
    Inject ``x-tenant-id`` into gRPC metadata.

    Resolution order:

    1. ``request.tenant.id`` if it exists.
    2. The header configured by ``GRPC_ADMIN_TENANT_HEADER`` (default
       ``x-tenant-id``) read from ``request.META``.
    """

    def __call__(self, request: Any) -> dict[str, str]:
        tenant_id = None
        tenant = getattr(request, "tenant", None)
        if tenant is not None:
            tenant_id = getattr(tenant, "id", None)

        if tenant_id is None:
            header_name = _django_setting("GRPC_ADMIN_TENANT_HEADER", "x-tenant-id")
            meta_key = (
                header_name.upper().replace("-", "_")
                if not header_name.startswith("HTTP_")
                else header_name
            )
            tenant_id = request.META.get(f"HTTP_{meta_key}") or request.META.get(meta_key)

        if tenant_id:
            return {"x-tenant-id": str(tenant_id)}
        return {}


class AuthTokenProvider:
    """Inject the HTTP ``authorization`` header into gRPC metadata."""

    def __call__(self, request: Any) -> dict[str, str]:
        auth = request.META.get("HTTP_AUTHORIZATION")
        if auth:
            return {"authorization": auth}
        return {}


class CorrelationIdProvider:
    """
    Inject ``x-request-id`` into gRPC metadata.

    If the request already carries an ``X-Request-ID`` header, reuse it;
    otherwise generate a new UUID. The value is also stored on
    ``request._grpc_request_id`` so audit logs can reference it.
    """

    def __call__(self, request: Any) -> dict[str, str]:
        request_id = request.META.get("HTTP_X_REQUEST_ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        request._grpc_request_id = request_id
        return {"x-request-id": request_id}
