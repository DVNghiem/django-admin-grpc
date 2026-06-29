"""
Pluggable audit/change tracking for django-admin-grpc write operations.

Audit events are emitted for every create, update, and delete performed through
``GrpcResourceAdmin``. Backends are swappable via the
``GRPC_ADMIN_AUDIT_BACKEND`` setting.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, cast

from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class AuditEvent:
    """
    A single audit event describing an admin write operation.

    Attributes:
        resource_name: Name of the resource affected.
        operation: One of ``create``, ``update``, ``delete``.
        pk: Primary key of the affected record (``None`` when unknown).
        user: User identifier (usually ``request.user``).
        timestamp: UTC timestamp when the event was emitted.
        before: Dict representation of the record before the change.
        after: Dict representation of the record after the change.
        diff: Dict describing changed fields.
        success: Whether the operation succeeded.
        error: Error message if ``success`` is ``False``.
        request_id: Correlation/request id.
        extra: Arbitrary extra context.
    """

    resource_name: str
    operation: str
    pk: Any
    user: str | None
    timestamp: datetime
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    diff: dict[str, Any] | None
    success: bool
    error: str | None
    request_id: str | None
    extra: dict[str, Any] | None


class BaseAuditBackend(ABC):
    """Abstract backend that persists and queries audit events."""

    @abstractmethod
    def log(self, event: AuditEvent) -> None:
        """Persist *event*."""
        ...

    @abstractmethod
    def query(self, **filters: Any) -> list[AuditEvent]:
        """
        Return audit events matching *filters*.

        Supported filters are backend-specific. Common keys include
        ``resource_name``, ``operation``, ``user``, ``request_id``,
        ``success``, ``pk``, ``since``, and ``until``.
        """
        ...


class LoggingAuditBackend(BaseAuditBackend):
    """Default backend that writes structured JSON to ``django_admin_grpc.audit``."""

    def __init__(self, logger_name: str = "django_admin_grpc.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    def log(self, event: AuditEvent) -> None:
        payload = dataclasses.asdict(event)
        payload["timestamp"] = event.timestamp.isoformat()
        self._logger.info(json.dumps(payload, default=str))

    def query(self, **filters: Any) -> list[AuditEvent]:
        # The logging backend is write-only; querying is not supported.
        return []


class DjangoModelAuditBackend(BaseAuditBackend):
    """Backend that stores audit events in the ``GrpcAuditLog`` model."""

    def log(self, event: AuditEvent) -> None:
        from django_admin_grpc.models import GrpcAuditLog

        GrpcAuditLog.objects.create(
            resource_name=event.resource_name,
            operation=event.operation,
            pk_value="" if event.pk is None else str(event.pk),
            user=event.user or "",
            timestamp=event.timestamp,
            before=event.before,
            after=event.after,
            diff=event.diff,
            success=event.success,
            error=event.error or "",
            request_id=event.request_id or "",
            extra=event.extra,
        )

    def query(self, **filters: Any) -> list[AuditEvent]:
        from django_admin_grpc.models import GrpcAuditLog

        qs = GrpcAuditLog.objects.all()
        if "resource_name" in filters:
            qs = qs.filter(resource_name=filters["resource_name"])
        if "operation" in filters:
            qs = qs.filter(operation=filters["operation"])
        if "user" in filters:
            qs = qs.filter(user=filters["user"] or "")
        if "request_id" in filters:
            qs = qs.filter(request_id=filters["request_id"] or "")
        if "success" in filters:
            qs = qs.filter(success=filters["success"])
        if "pk" in filters:
            qs = qs.filter(pk_value=str(filters["pk"]))
        if "since" in filters:
            qs = qs.filter(timestamp__gte=filters["since"])
        if "until" in filters:
            qs = qs.filter(timestamp__lte=filters["until"])
        limit = filters.get("limit")
        if limit is not None:
            qs = qs[:limit]
        return [item.to_audit_event() for item in qs]


class CompositeAuditBackend(BaseAuditBackend):
    """Backend that fans out audit events to multiple backends."""

    def __init__(self, backends: list[BaseAuditBackend] | None = None) -> None:
        self.backends = list(backends or [])

    def log(self, event: AuditEvent) -> None:
        for backend in self.backends:
            try:
                backend.log(event)
            except Exception:
                logger.exception("Audit backend %s failed to log event", backend)

    def query(self, **filters: Any) -> list[AuditEvent]:
        seen: set[tuple[Any, ...]] = set()
        results: list[AuditEvent] = []
        for backend in self.backends:
            try:
                for event in backend.query(**filters):
                    key = (
                        event.resource_name,
                        event.operation,
                        event.pk,
                        event.request_id,
                        event.timestamp,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(event)
            except Exception:
                logger.exception("Audit backend %s failed to query events", backend)
        return results


def load_audit_backend(value: Any | None = None) -> BaseAuditBackend:
    """Load the configured audit backend from a dotted path or instance."""
    from django_admin_grpc.settings import get_setting

    if value is None:
        value = get_setting("GRPC_ADMIN_AUDIT_BACKEND")
    if value is None:
        return LoggingAuditBackend()
    if isinstance(value, BaseAuditBackend):
        return value
    if isinstance(value, type) and issubclass(value, BaseAuditBackend):
        return value()
    if isinstance(value, str):
        backend_class = import_string(value)
        return cast(BaseAuditBackend, backend_class())
    raise ValueError(f"Invalid audit backend configuration: {value!r}")
