"""
Django admin integration for gRPC-backed resources.

``GrpcResourceAdmin`` is a ``ModelAdmin`` subclass that fetches data from a
remote gRPC service instead of the ORM.  It uses ``BaseGrpcResource`` for
metadata and ``BaseGrpcServiceAdapter`` for transport.
"""

from __future__ import annotations

import asyncio
import atexit
import csv
import functools
import hashlib
import inspect
import io
import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode

from django.apps import apps
from django.contrib import messages
from django.contrib.admin import ModelAdmin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import PermissionDenied
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
    StreamingHttpResponse,
)
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.async_adapter import BaseAsyncGrpcServiceAdapter
from django_admin_grpc.audit import (
    AuditEvent,
    BaseAuditBackend,
    load_audit_backend,
)
from django_admin_grpc.exceptions import (
    GrpcAdminError,
    GrpcBatchPartialError,
    get_grpc_error_message,
)
from django_admin_grpc.models import GrpcFakeQuerySet, ModelWrapper
from django_admin_grpc.paginator import GrpcPaginator, PagedResult, compute_filter_fingerprint
from django_admin_grpc.resources import BaseGrpcResource
from django_admin_grpc.settings import get_setting

logger = logging.getLogger(__name__)


def grpc_action(
    function: Callable[..., Any] | None = None,
    *,
    description: str = "",
    permissions: list[str] | None = None,
) -> Callable[..., Any]:
    """Decorator for gRPC admin actions.

    Wraps a method so it receives ``selected_pks`` (a list of primary keys)
    instead of a Django queryset, making it easier to work with gRPC bulk
    operations.

    Usage::

        class ProductAdmin(GrpcResourceAdmin):
            actions = ["activate_selected"]

            @grpc_action(description="Activate selected products")
            def activate_selected(self, request, selected_pks):
                updated, errors = self.apply_grpc_bulk_update(
                    request, selected_pks, {"active": True}
                )
                if updated:
                    messages.success(request, f"Activated {updated} product(s).")

    The decorated method is automatically exposed by Django's
    ``ModelAdmin.get_actions()`` when listed in ``actions``.

    Args:
        description: Human-readable label shown in the admin action dropdown.
            Defaults to the method name with underscores replaced by spaces.
        permissions: Optional list of permission codenames required to use
            this action (e.g. ``["change_product"]``).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, request: HttpRequest, queryset: Any) -> Any:
            selected_pks = self.get_grpc_selected_pks(request, queryset)
            return func(self, request, selected_pks)

        wrapper.short_description = description or getattr(  # type: ignore[attr-defined]
            func, "short_description", func.__name__.replace("_", " ").capitalize()
        )
        if permissions is not None:
            wrapper.allowed_permissions = permissions  # type: ignore[attr-defined]
        return wrapper

    if function is None:
        return decorator
    return decorator(function)


def bulk_grpc_action(
    description: str = "",
    *,
    field: str = "",
    value: Any = None,
    permissions: list[str] | None = None,
) -> Callable[..., Any]:
    """
    Decorator that turns a method into a single-field bulk update action.

    The decorated method receives ``selected_pks`` and delegates to
    :meth:`GrpcResourceAdmin.apply_grpc_bulk_update` with ``{field: value}``.
    A typical use is to bulk-toggle a flag (e.g. ``active=True``) on the
    currently selected rows::

        class ProductAdmin(GrpcResourceAdmin):
            actions = ["bulk_activate"]

            @bulk_grpc_action(description="Activate selected", field="active", value=True)
            def bulk_activate(self, request, selected_pks):
                # custom side effects allowed; the decorator wraps the body
                # so the field/value pair is applied automatically.
                ...

    Both bare and parenthesised invocations are supported::

        @bulk_grpc_action
        def my_action(self, request, selected_pks): ...

        @bulk_grpc_action(description="x", field="y", value=1)
        def my_action(self, request, selected_pks): ...

    Args:
        description: Human-readable label for the admin action dropdown.
        field: Field name to set on every selected record.
        value: Value to assign to *field*.
        permissions: Optional list of permission codenames.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, request: HttpRequest, queryset: Any) -> Any:
            selected_pks = self.get_grpc_selected_pks(request, queryset)
            # Apply the field/value update first; the body can layer on top.
            if field:
                self.apply_grpc_bulk_update(request, selected_pks, {field: value})
            return func(self, request, selected_pks)

        wrapper.short_description = description or getattr(  # type: ignore[attr-defined]
            func, "short_description", func.__name__.replace("_", " ").capitalize()
        )
        wrapper.grpc_bulk_field = field  # type: ignore[attr-defined]
        wrapper.grpc_bulk_value = value  # type: ignore[attr-defined]
        if permissions is not None:
            wrapper.allowed_permissions = permissions  # type: ignore[attr-defined]
        return wrapper

    # Allow bare decorator usage: @bulk_grpc_action
    if callable(description):
        func = description
        description = ""
        return decorator(func)
    return decorator


class ExportMixin:
    """
    Adds CSV and Excel export actions to ``GrpcResourceAdmin``.

    The mixin respects active list filters and fetches all pages until the
    result set is exhausted or ``export_max_rows`` is reached.
    """

    export_fields: list[str] | None = None
    export_max_rows: int = 10000
    export_filename_prefix: str = ""

    def has_export_permission(self, request: HttpRequest) -> bool:
        """Return ``True`` if the user may export records."""
        return self.has_view_permission(request)

    def export_as_csv(self, request: HttpRequest, queryset: Any) -> HttpResponse:
        """Export the current filtered result set as a UTF-8 CSV file."""
        if not self.has_export_permission(request):
            return HttpResponseForbidden("Export not allowed.")

        fields = self._get_export_fields(request)
        rows = self._fetch_all_for_export(request)
        headers = [self._get_export_header(f) for f in fields]
        filename = self._export_filename("csv")

        def _generate() -> Any:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(headers)
            yield buffer.getvalue().encode("utf-8-sig")
            buffer.seek(0)
            buffer.truncate(0)
            for row in rows:
                writer.writerow([self._export_value(row, f) for f in fields])
                yield buffer.getvalue().encode("utf-8")
                buffer.seek(0)
                buffer.truncate(0)

        response = StreamingHttpResponse(_generate(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def export_as_excel(self, request: HttpRequest, queryset: Any) -> HttpResponse:
        """Export the current filtered result set as an Excel workbook."""
        if not self.has_export_permission(request):
            return HttpResponseForbidden("Export not allowed.")

        try:
            import openpyxl
        except ImportError as exc:
            raise ImportError("Install openpyxl to use Excel export: pip install openpyxl") from exc

        fields = self._get_export_fields(request)
        rows = self._fetch_all_for_export(request)
        headers = [self._get_export_header(f) for f in fields]

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = self._fake_model._meta.verbose_name[:31] or "Export"
        worksheet.append(headers)
        for row in rows:
            worksheet.append([self._export_value(row, f) for f in fields])

        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)

        filename = self._export_filename("xlsx")
        response = HttpResponse(
            output.read(),
            content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def _get_export_fields(self, request: HttpRequest) -> list[str]:
        if self.export_fields:
            return list(self.export_fields)
        display = self.get_list_display(request)
        # ``get_list_display`` may return the action checkbox pseudo-field.
        return [f for f in display if isinstance(f, str) and f != "action_checkbox"]

    def _get_export_header(self, field_name: str) -> str:
        config = self._resource_class.get_field_config(field_name)
        if config is not None:
            return str(config.label or config.name)
        return field_name.replace("_", " ").title()

    def _export_value(self, row: Any, field_name: str) -> str:
        value = getattr(row, field_name, None)
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, default=str)
        return str(value)

    def _export_filename(self, extension: str) -> str:
        prefix = self.export_filename_prefix
        model_name = (
            getattr(self, "_fake_model", None) and self._fake_model._meta.model_name or "export"
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}{model_name}_{timestamp}.{extension}"

    def _fetch_all_for_export(self, request: HttpRequest) -> list[Any]:
        filters = self.get_grpc_filters(request)
        search_query = request.GET.get("q", "")
        if search_query:
            filters["search"] = search_query

        page_size = get_setting("GRPC_ADMIN_MAX_PAGE_SIZE") or 100
        max_rows = self.export_max_rows
        rows: list[Any] = []
        is_cursor = getattr(self, "grpc_cursor_pagination", False)
        page = 1

        while len(rows) < max_rows:
            result = self.fetch_list(
                page=page,
                page_size=page_size,
                filters=filters,
                request=request,
            )
            items = result.items if isinstance(result, PagedResult) else result.get("items", [])
            if not items:
                break
            rows.extend(items)
            if is_cursor:
                next_cursor = (
                    result.next_cursor
                    if isinstance(result, PagedResult)
                    else result.get("next_cursor")
                )
                if next_cursor:
                    filters["cursor"] = next_cursor
                    continue
                break
            page += 1

        return rows[:max_rows]

    def _add_export_actions(self, request: HttpRequest, actions: dict[str, Any]) -> None:
        if not self.has_export_permission(request):
            return
        actions["export_as_csv"] = (
            self.__class__.export_as_csv,
            "export_as_csv",
            "Export selected %(verbose_name_plural)s as CSV",
        )
        actions["export_as_excel"] = (
            self.__class__.export_as_excel,
            "export_as_excel",
            "Export selected %(verbose_name_plural)s as Excel",
        )


export_as_csv = ExportMixin.export_as_csv
export_as_excel = ExportMixin.export_as_excel


class AuditMixin:
    """
    Capture audit events for every admin write operation.

    The mixin wraps ``_adapter_create``, ``_adapter_update`` and
    ``_adapter_delete`` so that before/after snapshots are logged. Failed
    operations are logged with ``success=False``.
    """

    audit_backend: BaseAuditBackend | type[BaseAuditBackend] | str | None = None
    audit_enabled: bool = True
    auto_configure_from_proto: bool = False
    auto_configure_from_proto_options: dict[str, Any] | None = None

    _audit_local = threading.local()

    def _get_audit_request(self) -> HttpRequest | None:
        return getattr(self._audit_local, "request", None)

    def _set_audit_request(self, request: HttpRequest) -> None:
        self._audit_local.request = request

    def _clear_audit_request(self) -> None:
        self._audit_local.request = None

    def _audit_request_context(self, request: HttpRequest) -> Any:
        """Context manager that binds *request* to the audit thread-local."""
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            self._set_audit_request(request)
            try:
                yield
            finally:
                self._clear_audit_request()

        return _cm()

    def get_audit_backend(self) -> BaseAuditBackend:
        """Return the resolved audit backend instance for this admin."""
        cache_attr = "_audit_backend_instance"
        backend = getattr(self, cache_attr, None)
        if backend is not None:
            return backend

        configured = self.audit_backend
        if configured is None:
            configured = load_audit_backend()
        backend = load_audit_backend(configured)
        setattr(self, cache_attr, backend)
        return backend

    def audit_extra_context(self, request: HttpRequest | None) -> dict[str, Any]:
        """Return extra metadata to attach to every audit event."""
        return {}

    def _audit_user(self, request: HttpRequest | None) -> str | None:
        if request is None:
            return None
        user = getattr(request, "user", None)
        if user is None:
            return None
        if hasattr(user, "get_username"):
            username = user.get_username()
            if username:
                return username
            return None
        username = str(user)
        return username if username else None

    def _audit_request_id(self, request: HttpRequest | None) -> str | None:
        if request is None:
            return None
        rid = getattr(request, "_grpc_request_id", None)
        if rid:
            return rid
        return request.META.get("HTTP_X_REQUEST_ID") or str(uuid.uuid4())

    def _audit_now(self) -> datetime:

        return datetime.now(UTC)

    def _audit_diff(
        self,
        operation: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if operation == "create":
            return after
        if operation == "delete":
            return before
        if not isinstance(before, dict) or not isinstance(after, dict):
            return None
        diff: dict[str, Any] = {}
        keys = set(before.keys()) | set(after.keys())
        for key in keys:
            b = before.get(key)
            a = after.get(key)
            if b != a:
                diff[key] = {"before": b, "after": a}
        return diff or None

    def _log_audit_event(
        self,
        *,
        operation: str,
        pk: Any,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        success: bool,
        error: str | None,
    ) -> None:
        if not self.audit_enabled:
            return
        request = self._get_audit_request()
        event = AuditEvent(
            resource_name=getattr(self._resource_class, "__name__", str(self._resource_class)),
            operation=operation,
            pk=pk,
            user=self._audit_user(request),
            timestamp=self._audit_now(),
            before=before,
            after=after,
            diff=self._audit_diff(operation, before, after),
            success=success,
            error=error,
            request_id=self._audit_request_id(request),
            extra=self.audit_extra_context(request),
        )
        try:
            self.get_audit_backend().log(event)
        except Exception:
            logger.exception("Failed to log audit event")

    def _audit_fetch_before(
        self, adapter: Any, resource_class: type[BaseGrpcResource], pk: str
    ) -> dict[str, Any] | None:
        try:
            method = getattr(adapter, "get", None)
            if method is None:
                return None
            request = self._get_audit_request()
            if self._method_accepts_request(method):
                before_obj = method(resource_class, pk, request=request)
            else:
                before_obj = method(resource_class, pk)
            if inspect.iscoroutinefunction(method):
                before_obj = run_async(before_obj)
            if before_obj is not None and hasattr(before_obj, "to_dict"):
                return before_obj.to_dict()
            return None
        except Exception:
            return None

    def _audit_fetch_before_list(
        self,
        adapter: Any,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],
    ) -> list[dict[str, Any]]:
        """Return before-snapshots for *pks*, ignoring failures."""
        before: list[dict[str, Any]] = []
        for pk in pks:
            snapshot = self._audit_fetch_before(adapter, resource_class, str(pk))
            if snapshot is not None:
                before.append(snapshot)
        return before

    @staticmethod
    def _method_accepts_request(method: Callable[..., Any]) -> bool:
        try:
            return "request" in inspect.signature(method).parameters
        except (TypeError, ValueError):
            return False

    def _adapter_create(
        self,
        adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter,
        resource_class: type[BaseGrpcResource],
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Create a record and emit an audit event."""
        try:
            method = adapter.create
            request = self._get_audit_request()
            if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
                if self._method_accepts_request(method):
                    created = run_async(method(resource_class, data, request=request))
                else:
                    created = run_async(method(resource_class, data))
            elif self._method_accepts_request(method):
                created = method(resource_class, data, request=request)
            else:
                created = method(resource_class, data)
            created = cast(BaseGrpcResource, created)
            self._log_audit_event(
                operation="create",
                pk=getattr(created, "pk", None),
                before=None,
                after=created.to_dict() if hasattr(created, "to_dict") else None,
                success=True,
                error=None,
            )
            return created
        except Exception as exc:
            self._log_audit_event(
                operation="create",
                pk=None,
                before=None,
                after=None,
                success=False,
                error=str(exc),
            )
            raise

    def _adapter_update(
        self,
        adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter,
        resource_class: type[BaseGrpcResource],
        pk: str,
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Update a record and emit an audit event."""
        before = self._audit_fetch_before(adapter, resource_class, pk)
        try:
            method = adapter.update
            request = self._get_audit_request()
            if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
                if self._method_accepts_request(method):
                    updated = run_async(method(resource_class, pk, data, request=request))
                else:
                    updated = run_async(method(resource_class, pk, data))
            elif self._method_accepts_request(method):
                updated = method(resource_class, pk, data, request=request)
            else:
                try:
                    updated = method(resource_class, pk=pk, data=data)
                except TypeError:
                    updated = method(resource_class, pk, data)
            updated = cast(BaseGrpcResource, updated)
            self._log_audit_event(
                operation="update",
                pk=pk,
                before=before,
                after=updated.to_dict() if hasattr(updated, "to_dict") else None,
                success=True,
                error=None,
            )
            return updated
        except Exception as exc:
            self._log_audit_event(
                operation="update",
                pk=pk,
                before=before,
                after=None,
                success=False,
                error=str(exc),
            )
            raise

    def _adapter_delete(
        self,
        adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> bool:
        """Delete a record and emit an audit event."""
        before = self._audit_fetch_before(adapter, resource_class, pk)
        try:
            method = adapter.delete
            request = self._get_audit_request()
            if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
                if self._method_accepts_request(method):
                    result = run_async(method(resource_class, pk, request=request))
                else:
                    result = run_async(method(resource_class, pk))
            elif self._method_accepts_request(method):
                result = method(resource_class, pk, request=request)
            else:
                result = method(resource_class, pk)
            self._log_audit_event(
                operation="delete",
                pk=pk,
                before=before,
                after=None,
                success=True,
                error=None,
            )
            return cast(bool, result)
        except Exception as exc:
            self._log_audit_event(
                operation="delete",
                pk=pk,
                before=before,
                after=None,
                success=False,
                error=str(exc),
            )
            raise

    def add_view(
        self,
        request: HttpRequest,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        with self._audit_request_context(request):
            return super().add_view(request, form_url, extra_context)  # type: ignore[misc]

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        with self._audit_request_context(request):
            return super().change_view(request, object_id, form_url, extra_context)  # type: ignore[misc]

    def delete_view(
        self,
        request: HttpRequest,
        object_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        with self._audit_request_context(request):
            return super().delete_view(request, object_id, extra_context)  # type: ignore[misc]

    def apply_grpc_bulk_update(
        self,
        request: HttpRequest,
        queryset: Any,
        data: dict[str, Any],
    ) -> tuple[int, int]:
        with self._audit_request_context(request):
            return super().apply_grpc_bulk_update(request, queryset, data)  # type: ignore[misc]

    def apply_grpc_bulk_delete(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> dict[str, Any] | None:
        with self._audit_request_context(request):
            return super().apply_grpc_bulk_delete(request, queryset)  # type: ignore[misc]

    def bulk_create_action(self, request: HttpRequest, queryset: Any) -> None:
        with self._audit_request_context(request):
            super().bulk_create_action(request, queryset)  # type: ignore[misc]

    def bulk_update_action(self, request: HttpRequest, queryset: Any) -> None:
        with self._audit_request_context(request):
            super().bulk_update_action(request, queryset)  # type: ignore[misc]


class BulkActionMixin:
    """
    Adds bulk actions on top of :class:`GrpcResourceAdmin`.

    The mixin is applied automatically — ``GrpcResourceAdmin`` already
    inherits from it — but you can subclass it on a custom admin base to
    tweak the behaviour (e.g. disable ``bulk_create_action`` for read-only
    resources).

    Provided actions:

    * ``bulk_delete_action`` — always available; delegates to
      :meth:`apply_grpc_bulk_delete` which uses the adapter's ``bulk_delete``.
    * ``bulk_create_action`` — opt-in; only added when
      ``grpc_bulk_create_enabled = True`` on the admin.
    * ``bulk_update_action`` — opt-in; only added when
      ``grpc_bulk_update_enabled = True`` on the admin.

    The mixin also guarantees that the default ``delete_selected`` action
    is removed in :meth:`get_actions`.
    """

    #: Set to ``True`` to expose ``bulk_create_action`` in the actions list.
    grpc_bulk_create_enabled: bool = False
    #: Set to ``True`` to expose ``bulk_update_action`` in the actions list.
    grpc_bulk_update_enabled: bool = False

    # ``_resource_class`` is normally set on ``GrpcResourceAdmin.__init__``
    # but type checkers need an explicit declaration on the mixin so the
    # helper methods below can reference it.
    _resource_class: type[BaseGrpcResource]  # type: ignore[assignment]

    # ── Action wrappers (named so Django's get_actions can discover them) ──

    def bulk_delete_action(self, request: HttpRequest, queryset: Any) -> None:
        """
        Built-in admin action that deletes every selected row.

        Unlike Django's default ``delete_selected``, this path calls
        :meth:`apply_grpc_bulk_delete` which honours the adapter's
        ``batch_size`` and posts Django messages on partial failure (the
        underlying :class:`GrpcBatchPartialError` is consumed internally
        and is not re-raised).
        """
        self.apply_grpc_bulk_delete(request, queryset)

    def bulk_create_action(self, request: HttpRequest, queryset: Any) -> None:
        """
        Opt-in admin action that creates one row per selected record.

        Subclasses may override to customise the payload, or override
        :meth:`build_bulk_create_payload` to reshape the data sent to the
        adapter.
        """
        items = list(self.build_bulk_create_payload(request, queryset))
        adapter = self.get_adapter()  # type: ignore[attr-defined]
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return
        created: list[BaseGrpcResource] = []
        try:
            if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
                # Async adapter: ``bulk_create`` is a coroutine.
                created = cast(
                    list[BaseGrpcResource],
                    run_async(
                        adapter.bulk_create(self._resource_class, items, request=request)  # type: ignore[attr-defined]
                    ),
                )
            else:
                if self._method_accepts_request(adapter.bulk_create):
                    created = adapter.bulk_create(self._resource_class, items, request=request)  # type: ignore[attr-defined]
                else:
                    created = adapter.bulk_create(self._resource_class, items)  # type: ignore[attr-defined]
        except GrpcBatchPartialError as exc:
            messages.warning(
                request,
                f"Created {len(exc.succeeded)} of {len(items)} record(s); "
                f"{len(exc.failed)} failed.",
            )
            self._log_audit_event(
                operation="bulk_create",
                pk=None,
                before=None,
                after=None,
                success=False,
                error=f"Partial failure: {len(exc.succeeded)} succeeded, {len(exc.failed)} failed",
            )
            return
        messages.success(request, f"Created {len(created)} record(s).")
        self._log_audit_event(
            operation="bulk_create",
            pk=None,
            before=None,
            after=[item.to_dict() for item in created] if created else None,
            success=True,
            error=None,
        )

    def bulk_update_action(self, request: HttpRequest, queryset: Any) -> None:
        """
        Opt-in admin action that updates the selected records with a
        shared payload built by :meth:`build_bulk_update_payload`.
        """
        items = list(self.build_bulk_update_payload(request, queryset))
        adapter = self.get_adapter()  # type: ignore[attr-defined]
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return
        selected_pks = self.get_grpc_selected_pks(request, queryset)  # type: ignore[attr-defined]
        before = self._audit_fetch_before_list(adapter, self._resource_class, selected_pks)
        updated: list[BaseGrpcResource] = []
        try:
            if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
                # Async adapter: ``bulk_update`` is a coroutine.
                updated = cast(
                    list[BaseGrpcResource],
                    run_async(
                        adapter.bulk_update(self._resource_class, items, request=request)  # type: ignore[attr-defined]
                    ),
                )
            else:
                if self._method_accepts_request(adapter.bulk_update):
                    updated = adapter.bulk_update(self._resource_class, items, request=request)  # type: ignore[attr-defined]
                else:
                    updated = adapter.bulk_update(self._resource_class, items)  # type: ignore[attr-defined]
        except GrpcBatchPartialError as exc:
            messages.warning(
                request,
                f"Updated {len(exc.succeeded)} of {len(items)} record(s); "
                f"{len(exc.failed)} failed.",
            )
            self._log_audit_event(
                operation="bulk_update",
                pk=None,
                before=before or None,
                after=None,
                success=False,
                error=f"Partial failure: {len(exc.succeeded)} succeeded, {len(exc.failed)} failed",
            )
            return
        messages.success(request, f"Updated {len(updated)} record(s).")
        self._log_audit_event(
            operation="bulk_update",
            pk=None,
            before=before or None,
            after=[item.to_dict() for item in updated] if updated else None,
            success=True,
            error=None,
        )

    bulk_delete_action.short_description = (  # type: ignore[attr-defined]
        "Delete selected %(verbose_name_plural)s"
    )
    bulk_create_action.short_description = (  # type: ignore[attr-defined]
        "Create one record per selected %(verbose_name_plural)s"
    )
    bulk_update_action.short_description = (  # type: ignore[attr-defined]
        "Update selected %(verbose_name_plural)s"
    )

    # ── Hooks for subclasses to customise payloads ────────────────────────

    def build_bulk_create_payload(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> list[dict[str, Any]]:
        """
        Build the create payload for :meth:`bulk_create_action`.

        Default: empty ``{}`` per selected PK.  Subclasses should override
        to attach the data they want each new record to start with.
        """
        selected_pks = self.get_grpc_selected_pks(request, queryset)  # type: ignore[attr-defined]
        return [{} for _ in selected_pks]

    def build_bulk_update_payload(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> list[dict[str, Any]]:
        """
        Build the update payload for :meth:`bulk_update_action`.

        Default: ``{pk_field: pk}`` per selected PK so the adapter can
        identify the row but no fields are changed.  Subclasses should
        override to attach the fields they want updated.
        """
        selected_pks = self.get_grpc_selected_pks(request, queryset)  # type: ignore[attr-defined]
        pk_field = self._resource_class.Meta.pk_field  # type: ignore[attr-defined]
        return [{pk_field: pk} for pk in selected_pks]

    # ── gRPC-aware bulk delete helper ────────────────────────────────────

    def apply_grpc_bulk_delete(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> dict[str, Any] | None:
        """
        Delete selected records via the adapter's ``bulk_delete``.

        Supports both a Django queryset (standard actions) and a list of
        PKs (from :func:`grpc_action`).

        On full success, returns the adapter's ``{deleted, failed}`` summary.
        On partial failure, posts Django messages summarising the failure
        and returns ``None``; the underlying :class:`GrpcBatchPartialError`
        is consumed internally and not re-raised.
        """
        adapter = self.get_adapter()  # type: ignore[attr-defined]
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return None

        if isinstance(queryset, (list, tuple)):
            selected_pks: list[Any] = list(queryset)
        else:
            selected_pks = self.get_grpc_selected_pks(request, queryset)  # type: ignore[attr-defined]

        if not selected_pks:
            return {"deleted": 0, "failed": []}

        before = self._audit_fetch_before_list(adapter, self._resource_class, selected_pks)

        # Async adapters are not coroutines themselves; route through
        # ``run_async`` when the resolved adapter is async.
        if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
            try:
                result = cast(
                    dict[str, Any] | None,
                    run_async(
                        adapter.bulk_delete(self._resource_class, selected_pks, request=request)
                    ),
                )
            except GrpcBatchPartialError as exc:
                self._report_bulk_delete_failure(request, exc)
                self._log_audit_event(
                    operation="bulk_delete",
                    pk=None,
                    before=before or None,
                    after=None,
                    success=False,
                    error=f"Partial failure: {len(exc.succeeded)} succeeded, {len(exc.failed)} failed",
                )
                return None
        else:
            try:
                if self._method_accepts_request(adapter.bulk_delete):
                    result = adapter.bulk_delete(
                        self._resource_class, selected_pks, request=request
                    )  # type: ignore[attr-defined]
                else:
                    result = adapter.bulk_delete(self._resource_class, selected_pks)  # type: ignore[attr-defined]
            except GrpcBatchPartialError as exc:
                self._report_bulk_delete_failure(request, exc)
                self._log_audit_event(
                    operation="bulk_delete",
                    pk=None,
                    before=before or None,
                    after=None,
                    success=False,
                    error=f"Partial failure: {len(exc.succeeded)} succeeded, {len(exc.failed)} failed",
                )
                return None

        if result is None:
            # ``_report_bulk_delete_failure`` already posted messages.
            return None
        deleted_count = result.get("deleted", 0)
        if deleted_count:
            messages.success(
                request,
                f"Successfully deleted {deleted_count} record(s).",
            )
        self._log_audit_event(
            operation="bulk_delete",
            pk=None,
            before=before or None,
            after={"deleted": deleted_count},
            success=True,
            error=None,
        )
        return result

    def apply_grpc_bulk_update(
        self,
        request: HttpRequest,
        queryset: Any,
        data: dict[str, Any],
    ) -> tuple[int, int]:
        """
        Update selected records with the same payload via the adapter's
        ``update`` method.

        Supports both a Django queryset (standard actions) and a list of
        PKs (from :func:`grpc_action`).

        Returns a ``(updated_count, error_count)`` tuple.
        """
        adapter = self.get_adapter()  # type: ignore[attr-defined]
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return 0, 0

        # Support passing selected_pks directly (e.g. from @grpc_action)
        if isinstance(queryset, (list, tuple)):
            selected_pks = list(queryset)
        else:
            selected_pks = self.get_grpc_selected_pks(request, queryset)  # type: ignore[attr-defined]

        updated = 0
        errors = 0
        for pk in selected_pks:
            try:
                self._adapter_update(adapter, self._resource_class, pk, data)  # type: ignore[attr-defined]
                updated += 1
            except GrpcAdminError as exc:
                logger.warning("gRPC bulk update failed for pk=%s: %s", pk, exc)
                errors += 1
                level, message = get_grpc_error_message(exc)
                messages.add_message(request, level, message)
            except Exception as exc:
                logger.warning("gRPC bulk update failed for pk=%s: %s", pk, exc)
                errors += 1
        return updated, errors

    def _report_bulk_delete_failure(
        self,
        request: HttpRequest,
        exc: GrpcBatchPartialError,
    ) -> None:
        """Post Django messages summarising a partial bulk-delete failure."""
        deleted = len(exc.succeeded)
        failed_count = len(exc.failed)
        messages.error(
            request,
            f"Deleted {deleted} of {deleted + failed_count} record(s); {failed_count} failed.",
        )
        failed_items: Any = exc.failed
        if isinstance(failed_items, dict):
            for failed_pk, exc_obj in failed_items.items():
                self._post_delete_failure(request, failed_pk, exc_obj)
        else:
            for item in failed_items:
                self._post_delete_failure(request, None, item)

    def _post_delete_failure(
        self,
        request: HttpRequest,
        failed_pk: Any,
        exc_obj: Any,
    ) -> None:
        """Post a single Django message for a per-PK delete failure."""
        if isinstance(exc_obj, GrpcAdminError):
            level, message = get_grpc_error_message(exc_obj)
        else:
            level, message = messages.ERROR, str(exc_obj)
        try:
            messages.add_message(
                request,
                level,
                f"Delete failed for pk={failed_pk}: {message}",
            )
        except Exception:
            # No messages middleware installed (e.g. raw RequestFactory).
            # The summary error above is still posted, so the user sees
            # the count of failures even without the per-row detail.
            logger.debug(
                "messages.add_message failed; messages middleware missing?",
                exc_info=True,
            )


class GrpcChangeList(ChangeList):
    """
    Custom ``ChangeList`` that populates results by calling the adapter's
    ``list()`` method.
    """

    def __init__(
        self,
        request: HttpRequest,
        model: type,
        list_display: list[str],
        list_display_links: list[str],
        list_filter: list[Any],
        date_hierarchy: str | None,
        search_fields: list[str],
        list_select_related: bool,
        list_per_page: int,
        list_max_show_all: int,
        list_editable: list[str],
        model_admin: GrpcResourceAdmin,
        sortable_by: list[str],
        search_help_text: str,
    ):
        self._grpc_model_admin = model_admin
        self._grpc_list_filter = list_filter
        super().__init__(
            request,
            model,
            list_display,  # type: ignore[arg-type]
            list_display_links,  # type: ignore[arg-type]
            list_filter,
            date_hierarchy,
            search_fields,
            list_select_related,
            list_per_page,
            list_max_show_all,
            list_editable,
            model_admin,
            sortable_by,
            search_help_text,
        )
        filter_info = self.get_filters(request)
        self.filter_specs = filter_info[0]
        self.has_filters = filter_info[1]
        self.has_active_filters = filter_info[4] if len(filter_info) > 4 else bool(filter_info[2])

    def get_filters(self, request: HttpRequest) -> tuple:
        from django.contrib.admin import SimpleListFilter

        filter_specs: list[Any] = []
        lookup_params: dict[str, str] = {}
        params = dict(request.GET.items())

        if self._grpc_list_filter:
            for list_filter_item in self._grpc_list_filter:
                if isinstance(list_filter_item, type) and issubclass(
                    list_filter_item, SimpleListFilter
                ):
                    filter_spec: Any = list_filter_item(
                        request,
                        params,  # type: ignore[arg-type]
                        self.model,
                        self.model_admin,  # type: ignore[arg-type]
                    )
                    filter_specs.append(filter_spec)
                    continue

                if isinstance(list_filter_item, str):
                    field_path = list_filter_item
                    filter_config: dict[str, Any] = {}

                    model_admin = cast(GrpcResourceAdmin, self.model_admin)
                    rc = model_admin.resource_class
                    if rc is None:
                        continue
                    if hasattr(model_admin, "grpc_filter_config"):
                        gfc = model_admin.grpc_filter_config
                        if isinstance(gfc, dict) and field_path not in gfc:
                            continue
                        if isinstance(gfc, dict):
                            filter_config = gfc.get(field_path, {})
                        else:
                            # list format
                            fc = rc.get_field_config(field_path)
                            filter_config = {"type": fc.type if fc else "text"}

                    field_type = filter_config.get("type", "text")
                    choices_list = filter_config.get("choices")

                    if field_type == "boolean" or (field_type == "choices" and choices_list):
                        from django_admin_grpc.filters import create_grpc_filter_spec

                        filter_class = create_grpc_filter_spec(field_path, field_type, choices_list)
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": field_path.replace("_", " ").title(),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning("Failed to create filter for %s: %s", field_path, e)
                    elif field_type in ("number_range", "date_range"):
                        from django_admin_grpc.filters import (
                            GrpcDateRangeFilter,
                            GrpcNumberRangeFilter,
                        )

                        filter_class = (
                            GrpcNumberRangeFilter
                            if field_type == "number_range"
                            else GrpcDateRangeFilter
                        )
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": filter_config.get(
                                    "label",
                                    field_path.replace("_", " ").title(),
                                ),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create %s filter for %s: %s",
                                field_type,
                                field_path,
                                e,
                            )
                    elif field_type == "multi_choices" and choices_list:
                        from django_admin_grpc.filters import create_grpc_filter_spec

                        filter_class = create_grpc_filter_spec(field_path, field_type, choices_list)
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": field_path.replace("_", " ").title(),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create multi_choices filter for %s: %s",
                                field_path,
                                e,
                            )
                    elif field_type == "text":
                        from django_admin_grpc.filters import GrpcTextInputFilter

                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": filter_config.get(
                                    "label",
                                    field_path.replace("_", " ").title(),
                                ),
                            },
                        )()
                        try:
                            filter_spec = GrpcTextInputFilter(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create text filter for %s: %s",
                                field_path,
                                e,
                            )

        has_filters = bool(filter_specs)
        for filter_spec in filter_specs:
            try:
                for param in filter_spec.expected_parameters():
                    if param in request.GET:
                        lookup_params[param] = request.GET[param]
            except Exception:
                pass

        may_have_duplicates = False
        has_active_filters = bool(lookup_params)
        return (
            filter_specs,
            has_filters,
            lookup_params,
            may_have_duplicates,
            has_active_filters,
        )

    def get_queryset(  # type: ignore[override]
        self, request: HttpRequest
    ) -> GrpcFakeQuerySet:
        return GrpcFakeQuerySet(self.model)

    def get_results(self, request: HttpRequest) -> None:
        page_num = self.page_num or 1
        page_size = self.list_per_page
        filters = self._grpc_model_admin.get_grpc_filters(request)

        search_query = request.GET.get("q", "")
        if search_query:
            filters["search"] = search_query

        is_cursor = getattr(self._grpc_model_admin, "grpc_cursor_pagination", False)
        filter_fp = ""
        active_filters = bool(filters)
        if is_cursor:
            filter_fp = compute_filter_fingerprint(filters)
            incoming_fp = request.GET.get("__grpc_filter_fp")
            cursor = request.GET.get("cursor")
            if cursor and active_filters and incoming_fp != filter_fp:
                cursor = None
            if cursor:
                filters["cursor"] = cursor

        try:
            result = self._grpc_model_admin.fetch_list(
                page=page_num, page_size=page_size, filters=filters, request=request
            )
            items = result.items if isinstance(result, PagedResult) else result.get("items", [])
            total = (
                result.total if isinstance(result, PagedResult) else result.get("total", len(items))
            )
            next_cursor = (
                result.next_cursor
                if isinstance(result, PagedResult)
                else result.get("next_cursor", None)
            )

            fake_model = self._grpc_model_admin._fake_model
            fk_cache = self._grpc_model_admin._preload_fk_displays(request, items)
            self.result_list = [
                ModelWrapper(item, fake_model._meta, fk_display_cache=fk_cache) for item in items
            ]
            self.result_count = total
            self.full_result_count = total
            self.can_show_all = False
            self.multi_page = self.result_count > page_size

            self.paginator = GrpcPaginator(self.result_list, page_size, self.result_count)

            if is_cursor:
                self.grpc_next_cursor = next_cursor
                if next_cursor:
                    params = request.GET.copy()
                    params["cursor"] = next_cursor
                    params.pop("p", None)
                    if active_filters:
                        params["__grpc_filter_fp"] = filter_fp
                    else:
                        params.pop("__grpc_filter_fp", None)
                    self.cursor_next_url = "?" + urlencode(params)
                else:
                    self.cursor_next_url = None  # type: ignore[assignment]
                from django_admin_grpc.settings import get_setting

                self.paginator.template_name = (
                    get_setting("DEFAULT_CURSOR_PAGINATION_TEMPLATE")
                    or "django_admin_grpc/cursor_pagination.html"
                )

        except GrpcAdminError as exc:
            logger.exception("Error fetching gRPC data: %s", exc)
            self.result_list = []
            self.result_count = 0
            self.full_result_count = 0
            self.can_show_all = False
            self.multi_page = False
            self.paginator = GrpcPaginator([], page_size, 0)
            if is_cursor:
                self.cursor_next_url = None  # type: ignore[assignment]
            level, message = get_grpc_error_message(exc)
            messages.add_message(request, level, message)
        except Exception as e:
            logger.exception("Error fetching gRPC data: %s", e)
            self.result_list = []
            self.result_count = 0
            self.full_result_count = 0
            self.can_show_all = False
            self.multi_page = False
            self.paginator = GrpcPaginator([], page_size, 0)
            if is_cursor:
                self.cursor_next_url = None  # type: ignore[assignment]
            messages.info(request, "No data found or error fetching data.")


class GrpcResourceAdmin(AuditMixin, ExportMixin, BulkActionMixin, ModelAdmin):
    """
    Admin class for resources fetched from a gRPC service.

    Subclasses **must** set:

    * ``resource_class`` – a ``BaseGrpcResource`` subclass.
    * ``service_name`` **or** ``adapter_class`` – tells the admin how to reach
      the remote service.

    Optional attributes:

    * ``grpc_filter_config`` – dict or list describing filterable fields.
    * ``grpc_form_fields`` – list of field names to expose in add/change forms.
    * ``grpc_enable_create`` / ``grpc_enable_update`` / ``grpc_enable_delete``
    * ``grpc_detail_fields`` – fields shown in the read-only detail section.
    * ``grpc_cursor_pagination`` – use cursor-based pagination.
    * ``grpc_bulk_create_enabled`` / ``grpc_bulk_update_enabled`` – opt-in
      flags to expose ``bulk_create_action`` / ``bulk_update_action``.
    * ``auto_configure_from_proto`` – when ``True`` and the resource has a
      ``proto_descriptor``, fields are generated automatically on first use.

    Inherits :class:`AuditMixin` for write-operation auditing,
    :class:`ExportMixin` for CSV/Excel export actions, and
    :class:`BulkActionMixin` for built-in bulk operations.
    """

    resource_class: type[BaseGrpcResource] | None = None
    service_name: str = ""
    adapter_class: type[BaseGrpcServiceAdapter] | None = None

    verbose_name: str = ""
    verbose_name_plural: str = ""
    grpc_filter_config: dict[str, Any] | list[str] = {}
    grpc_form_fields: list[str] = []
    grpc_enable_create: bool = False
    grpc_enable_update: bool = False
    grpc_enable_delete: bool = False
    grpc_detail_fields: list[Any] = []
    grpc_cursor_pagination: bool = False

    def __init__(self, model: type[Any] | None = None, admin_site: Any | None = None) -> None:
        if self.resource_class is None:
            raise ValueError(f"{self.__class__.__name__} must define resource_class")
        self._resource_class: type[BaseGrpcResource] = self.resource_class

        if (
            self.auto_configure_from_proto
            and getattr(self._resource_class, "proto_descriptor", None) is not None
            and not self._resource_class.fields
        ):
            options = getattr(self, "auto_configure_from_proto_options", None) or {}
            self._resource_class.configure_fields_from_proto(**options)

        self._fake_model = self._resource_class.admin_model()
        super().__init__(self._fake_model, admin_site)  # type: ignore[arg-type]
        self._adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter | None = None

    # ── Template resolution ────────────────────────────────────────────────

    def _get_change_form_template(self) -> str:
        """Return the template path for add/change views.

        Resolution order:
        1. Resource Meta ``change_form_template``
        2. ``GRPC_ADMIN['DEFAULT_CHANGE_FORM_TEMPLATE']``
        3. Package default
        """
        resource_template = getattr(self._resource_class.Meta, "change_form_template", "")
        if resource_template:
            return cast(str, resource_template)
        from django_admin_grpc.settings import get_setting

        setting_template = get_setting("DEFAULT_CHANGE_FORM_TEMPLATE")
        if setting_template:
            return cast(str, setting_template)
        return "django_admin_grpc/change_form.html"

    def _get_delete_confirm_template(self) -> str:
        """Return the template path for the delete confirmation view.

        Resolution order:
        1. Resource Meta ``delete_confirm_template``
        2. ``GRPC_ADMIN['DEFAULT_DELETE_CONFIRM_TEMPLATE']``
        3. Package default
        """
        resource_template = getattr(self._resource_class.Meta, "delete_confirm_template", "")
        if resource_template:
            return cast(str, resource_template)
        from django_admin_grpc.settings import get_setting

        setting_template = get_setting("DEFAULT_DELETE_CONFIRM_TEMPLATE")
        if setting_template:
            return cast(str, setting_template)
        return "django_admin_grpc/delete_confirm.html"

    @classmethod
    def with_base(cls, base_admin_class: type) -> type[Any]:
        """Return a new admin class that inherits from the given base.

        Usage::

            class MyGrpcAdmin(GrpcResourceAdmin.with_base(UnfoldModelAdmin)):
                pass
        """
        return type(
            f"{cls.__name__}With{base_admin_class.__name__}",
            (cls, base_admin_class),
            {},
        )

    # ── Actions ────────────────────────────────────────────────────────────

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        if self._can_delete():
            # New name (preferred). Delegates to the BulkActionMixin
            # implementation.
            actions["bulk_delete_action"] = (  # type: ignore[assignment]
                self.__class__.bulk_delete_action,
                "bulk_delete_action",
                getattr(
                    self.bulk_delete_action,
                    "short_description",
                    "Delete selected %(verbose_name_plural)s",
                ),
            )
            # Legacy name kept for backward compatibility.
            actions["grpc_delete_selected"] = (  # type: ignore[assignment]
                self.__class__._grpc_delete_selected,
                "grpc_delete_selected",
                "Delete selected %(verbose_name_plural)s",
            )
        if getattr(self, "grpc_bulk_create_enabled", False) and self._can_create():
            actions["bulk_create_action"] = (  # type: ignore[assignment]
                self.__class__.bulk_create_action,
                "bulk_create_action",
                getattr(
                    self.bulk_create_action,
                    "short_description",
                    "Create one record per selected %(verbose_name_plural)s",
                ),
            )
        if getattr(self, "grpc_bulk_update_enabled", False) and self._can_update():
            actions["bulk_update_action"] = (  # type: ignore[assignment]
                self.__class__.bulk_update_action,
                "bulk_update_action",
                getattr(
                    self.bulk_update_action,
                    "short_description",
                    "Update selected %(verbose_name_plural)s",
                ),
            )
        self._add_export_actions(request, actions)
        return actions

    def _grpc_delete_selected(self, request: HttpRequest, queryset: Any) -> None:
        """
        Legacy bulk-delete entry point kept for backward compatibility.

        New code should use :meth:`BulkActionMixin.bulk_delete_action`
        (registered as ``bulk_delete_action`` in the actions dropdown).
        """
        # Delegate to the new bulk-delete helper; it already posts the
        # success/failure messages, so this wrapper does not duplicate them.
        self.apply_grpc_bulk_delete(request, queryset)

    _grpc_delete_selected.short_description = "Delete selected records"  # type: ignore[attr-defined]

    def get_grpc_selected_pks(self, request: HttpRequest, queryset: Any) -> list[Any]:
        selected = getattr(queryset, "_selected_pks", None) or request.POST.getlist(
            "_selected_action"
        )
        return list(selected or [])

    # ── Adapter plumbing ───────────────────────────────────────────────────

    def get_adapter(self) -> BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter | None:
        """Return the gRPC adapter for this admin."""
        if self._adapter is not None:
            return self._adapter
        if self.adapter_class is not None:
            if isinstance(self.adapter_class, type):
                self._adapter = self.adapter_class()
                return self._adapter
            self._adapter = self.adapter_class
            return self._adapter
        if self.service_name:
            from django_admin_grpc.registry import adapter_registry

            self._adapter = adapter_registry.get_adapter(self.service_name)
            return self._adapter
        return None

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type[GrpcChangeList]:
        return GrpcChangeList

    def get_queryset(  # type: ignore[override]
        self, request: HttpRequest
    ) -> GrpcFakeQuerySet:
        return GrpcFakeQuerySet(self._resource_class)

    def get_grpc_filters(self, request: HttpRequest) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        cfg = self.grpc_filter_config
        is_dict_config = isinstance(cfg, dict)
        if cfg is not None:
            if is_dict_config:
                filterable_fields = set(cast(dict[str, Any], cfg).keys())
            else:
                filterable_fields = set(cfg)
        else:
            filterable_fields = None

        filter_config_dict: dict[str, Any] = cast(dict[str, Any], cfg) if is_dict_config else {}

        for key in request.GET:
            if key in {
                "p",
                "o",
                "all",
                "_changelist_filters",
                "e",
                "q",
                "cursor",
                "__grpc_filter_fp",
            }:
                continue

            if filterable_fields is not None:
                if is_dict_config:
                    base_key = key.split("__")[0]
                    if base_key not in filterable_fields:
                        continue
                    config = filter_config_dict.get(base_key, {})
                    field_type = config.get("type", "text") if isinstance(config, dict) else "text"
                    suffix = key[len(base_key) :] if key.startswith(base_key) else ""
                    if (
                        field_type in ("number_range", "date_range")
                        and suffix
                        and suffix not in {"__gte", "__lte", "__gt", "__lt"}
                    ):
                        continue
                    if (
                        field_type == "multi_choices"
                        and suffix
                        and suffix not in {"", "__exact", "__in"}
                    ):
                        continue
                else:
                    if key not in filterable_fields:
                        continue

            if is_dict_config:
                base_key = key.split("__")[0]
                config = filter_config_dict.get(base_key, {})
                field_type = config.get("type", "text") if isinstance(config, dict) else "text"
                if field_type == "multi_choices":
                    values = request.GET.getlist(key)
                    parsed: list[str] = []
                    for v in values:
                        parsed.extend(v.split(","))
                    parsed = [v.strip() for v in parsed if v.strip()]
                    if parsed:
                        filters[key] = parsed
                    continue

            filters[key] = request.GET[key]

        return filters

    def fetch_list(
        self,
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
        request: HttpRequest | None = None,
    ) -> PagedResult | dict[str, Any]:
        adapter = self.get_adapter()
        if adapter is None:
            logger.warning("No gRPC adapter available for service: %s", self.service_name)
            return PagedResult(items=[])

        kwargs: dict[str, Any] = {"filters": filters or {}}
        if self.grpc_cursor_pagination:
            kwargs["page_size"] = page_size
        else:
            kwargs["page"] = page
            kwargs["page_size"] = page_size

        method = adapter.list
        if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
            if self._method_accepts_request(method):
                kwargs["request"] = request
            return cast(
                PagedResult | dict[str, Any],
                run_async(method(self._resource_class, **kwargs)),
            )
        if self._method_accepts_request(method):
            kwargs["request"] = request
        return cast(BaseGrpcServiceAdapter, adapter).list(self._resource_class, **kwargs)

    def fetch_one(self, pk: str, request: HttpRequest | None = None) -> ModelWrapper | None:
        adapter = self.get_adapter()
        if adapter is None:
            return None
        instance = self._adapter_get(adapter, self._resource_class, pk, request=request)
        if instance is None:
            return None
        return ModelWrapper(instance, self._fake_model._meta)

    def _adapter_get(
        self,
        adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter,
        resource_class: type[BaseGrpcResource],
        pk: str,
        method_name: str = "get",
        request: HttpRequest | None = None,
    ) -> BaseGrpcResource | None:
        """Hook for adapter ``get()``; overridden by async admin."""
        method = getattr(adapter, method_name)
        if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
            if self._method_accepts_request(method):
                return cast(
                    BaseGrpcResource | None, run_async(method(resource_class, pk, request=request))
                )
            return cast(BaseGrpcResource | None, run_async(method(resource_class, pk)))
        if self._method_accepts_request(method):
            try:
                return cast(BaseGrpcResource | None, method(resource_class, pk=pk, request=request))
            except TypeError:
                return cast(BaseGrpcResource | None, method(resource_class, pk, request=request))
        try:
            return cast(BaseGrpcResource | None, method(resource_class, pk=pk))
        except TypeError:
            return cast(BaseGrpcResource | None, method(resource_class, pk))

    def _adapter_batch_get(
        self,
        adapter: BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],
        request: HttpRequest | None = None,
    ) -> dict[Any, Any]:
        """Hook for adapter ``batch_get()``; handles async adapters via ``run_async``."""
        if isinstance(adapter, BaseAsyncGrpcServiceAdapter):
            if self._method_accepts_request(adapter.batch_get):
                return cast(
                    dict[Any, Any],
                    run_async(adapter.batch_get(resource_class, pks, request=request)),
                )
            return cast(dict[Any, Any], run_async(adapter.batch_get(resource_class, pks)))
        if self._method_accepts_request(adapter.batch_get):
            return cast(BaseGrpcServiceAdapter, adapter).batch_get(
                resource_class, pks, request=request
            )
        return cast(BaseGrpcServiceAdapter, adapter).batch_get(resource_class, pks)

    def _get_fk_adapter(
        self, service: str
    ) -> BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter | None:
        """Look up an FK service adapter from the sync registry, then the async one."""
        from django_admin_grpc.registry import adapter_registry

        adapter = adapter_registry.get_adapter(service)
        if adapter is not None:
            return adapter
        from django_admin_grpc.async_adapter import async_adapter_registry

        return async_adapter_registry.get_adapter(service)

    # ── FK display caching ─────────────────────────────────────────────────

    def _compute_fk_page_key(self, items: list[Any]) -> str:
        """Return a stable, order-independent key for *items*.

        The key includes each item's primary key plus the values of any
        service-backed FK fields. This prevents stale display maps when the same
        row PKs are rendered with different FK values in the same request.
        """
        from django_admin_grpc.resources import FKFieldConfig

        fk_fields = [
            fc.name
            for fc in self._resource_class.get_field_configs()
            if isinstance(fc, FKFieldConfig) and fc.service and not fc.model
        ]

        item_keys: list[str] = []
        for item in items:
            pk = getattr(item, "pk", None)
            if pk is None:
                pk = getattr(item, "id", None)
            if pk is None:
                pk = repr(item)

            parts = [str(pk)]
            for field_name in fk_fields:
                value = getattr(item, field_name, None)
                parts.append(f"{field_name}={value}")
            item_keys.append("|".join(parts))

        fingerprint = ",".join(sorted(item_keys))
        return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]

    def _preload_fk_displays(
        self,
        request: HttpRequest,
        items: list[Any],
    ) -> dict[str, dict[Any, Any]]:
        """
        Collect distinct service-backed FK values across *items* and resolve them
        with a single ``batch_get`` call per field.

        The resulting mapping is cached on *request* for the duration of the
        request so repeated list renders do not trigger additional lookups.
        """
        from django_admin_grpc.resources import FKFieldConfig

        if not items:
            return {}

        request_cache: dict[str, Any] = getattr(request, "_grpc_fk_cache", None) or {}
        if not request_cache:
            request._grpc_fk_cache = request_cache  # type: ignore[attr-defined]

        page_key = self._compute_fk_page_key(items)
        cache_key = f"{self._resource_class.__name__}_fk_displays_{page_key}"
        if cache_key in request_cache:
            return cast(dict[str, dict[Any, Any]], request_cache[cache_key])

        display_cache: dict[str, dict[Any, Any]] = {}

        for fc in self._resource_class.get_field_configs():
            if not isinstance(fc, FKFieldConfig):
                continue
            # Model-backed FKs are resolved by Django ORM; preload only service FKs.
            if not fc.service or fc.model or not fc.display_field:
                continue

            adapter = self._get_fk_adapter(fc.service)
            if adapter is None:
                logger.warning(
                    "No gRPC adapter registered for service=%s field=%s",
                    fc.service,
                    fc.name,
                )
                continue

            fk_ids: set[Any] = set()
            for item in items:
                raw_value = getattr(item, fc.name, None)
                if raw_value is not None and raw_value != "":
                    fk_ids.add(raw_value)
            if not fk_ids:
                continue

            # Use the FK target resource class when configured, otherwise fall back
            # to the row resource class for backward compatibility.
            related_resource_class = fc.resource_class or self._resource_class

            has_custom_batch_get = hasattr(adapter, "batch_get") and getattr(
                type(adapter), "batch_get", None
            ) not in (BaseGrpcServiceAdapter.batch_get, BaseAsyncGrpcServiceAdapter.batch_get)

            resolved: dict[Any, Any] = {}
            if has_custom_batch_get:
                try:
                    resolved = self._adapter_batch_get(
                        adapter, related_resource_class, list(fk_ids)
                    )
                except Exception as exc:
                    logger.warning("Failed to batch_get FK values for field %s: %s", fc.name, exc)
                    continue
            else:
                # Backward-compatible fallback: loop the configured get_method.
                get_method = getattr(fc, "get_method", "get") or "get"
                for fk_id in fk_ids:
                    try:
                        related = self._adapter_get(
                            adapter, related_resource_class, str(fk_id), get_method
                        )
                        resolved[fk_id] = related
                    except Exception as exc:
                        logger.warning(
                            "Failed to resolve FK value for field %s pk=%s: %s",
                            fc.name,
                            fk_id,
                            exc,
                        )

            field_cache: dict[Any, Any] = {}
            for fk_id, related in resolved.items():
                if related is None:
                    field_cache[fk_id] = None
                else:
                    field_cache[fk_id] = getattr(related, fc.display_field, str(related))
            display_cache[fc.name] = field_cache

        request_cache[cache_key] = display_cache
        return display_cache

    # ── Permission helpers ─────────────────────────────────────────────────

    def _has_form_fields(self) -> bool:
        return bool(self.grpc_form_fields)

    def _adapter_supports_create(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_create

    def _adapter_supports_update(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_update

    def _adapter_supports_delete(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_delete

    def _can_create(self) -> bool:
        return (
            self.grpc_enable_create and self._has_form_fields() and self._adapter_supports_create()
        )

    def _can_update(self) -> bool:
        return (
            self.grpc_enable_update and self._has_form_fields() and self._adapter_supports_update()
        )

    def _can_delete(self) -> bool:
        return self.grpc_enable_delete and self._adapter_supports_delete()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return self.has_grpc_add_permission(request) and self._can_create()

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return (
            self.has_grpc_change_permission(request, obj=obj)
            and self.has_view_permission(request, obj=obj)
            and self._can_update()
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_grpc_delete_permission(request, obj=obj) and self._can_delete()

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_grpc_view_permission(request, obj=obj)

    def has_grpc_add_permission(self, request: HttpRequest) -> bool:
        return True

    def has_grpc_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    def has_grpc_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    def has_grpc_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    # ── Forms ──────────────────────────────────────────────────────────────

    def _build_form_class(self) -> type[Any]:
        from django_admin_grpc.forms import FormBuilder
        from django_admin_grpc.widgets import get_default_widgets

        return FormBuilder.build(
            self._resource_class,
            widgets=get_default_widgets(),
            field_names=self.grpc_form_fields or None,
        )

    def clean_grpc_data(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(data)
        for field_name, value in list(cleaned.items()):
            field_cleaner = getattr(self, f"clean_{field_name}", None)
            if callable(field_cleaner):
                cleaned[field_name] = field_cleaner(value)
        return self.clean(cleaned)

    def clean(self, data: dict[str, Any]) -> dict[str, Any]:
        return data

    def get_grpc_form_initial(self, obj: Any) -> dict[str, Any]:
        return {field_name: getattr(obj, field_name, None) for field_name in self.grpc_form_fields}

    def get_grpc_create_data(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return cleaned_data

    def get_grpc_update_data(self, obj: Any, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return cleaned_data

    # ── Detail rows ────────────────────────────────────────────────────────

    def get_grpc_detail_fields(self) -> list[tuple[str, str]]:
        if self.grpc_detail_fields:
            if (
                isinstance(self.grpc_detail_fields[0], (list, tuple))
                and len(self.grpc_detail_fields[0]) == 2
            ):
                return list(self.grpc_detail_fields)
            fields: list[tuple[str, str]] = []
            for fn in self.grpc_detail_fields:
                fc = self._resource_class.get_field_config(str(fn))
                label = str(fc.label) if fc is not None else str(fn).replace("_", " ").title()
                fields.append((label, str(fn)))
            return fields
        return [
            (fc.label or fc.name, fc.name)
            for fc in self._resource_class.get_field_configs()
            if not fc.list_only
        ]

    def get_grpc_detail_rows(self, obj: Any) -> list[dict[str, Any]]:
        from django_admin_grpc.resources import FKFieldConfig

        rows: list[dict[str, Any]] = []
        for label, field_name in self.get_grpc_detail_fields():
            value = getattr(obj, field_name, None)
            config = self._resource_class.get_field_config(field_name)
            is_fk = config is not None and isinstance(config, FKFieldConfig)
            resolved_value = value
            if is_fk and value is not None:
                resolved = self.resolve_fk_value(field_name, config, value)
                if resolved is not None:
                    resolved_value = resolved
            rows.append(
                {
                    "label": label,
                    "field_name": field_name,
                    "value": resolved_value,
                    "is_boolean": isinstance(value, bool),
                    "is_fk": is_fk,
                }
            )
        return rows

    def resolve_fk_value(
        self,
        field_name: str,
        config: Any,
        fk_id: Any,
    ) -> str | None:
        from django_admin_grpc.resources import FKFieldConfig

        if config is None or not isinstance(config, FKFieldConfig):
            return fk_id if fk_id is not None else None  # type: ignore[return-value]
        if not config.display_field:
            return fk_id if fk_id is not None else None  # type: ignore[return-value]
        if not fk_id:
            return None

        # Django model lookup
        if getattr(config, "model", None):
            model_path = cast(str, config.model)
            try:
                app_label, model_name = model_path.split(".")
                model = apps.get_model(app_label, model_name)
                obj = model.objects.get(pk=fk_id)
                return str(getattr(obj, config.display_field, str(obj)))
            except (ValueError, LookupError) as e:
                logger.warning(
                    "resolve_fk_value: Django lookup failed for %s model=%s pk=%s: %s",
                    field_name,
                    model_path,
                    fk_id,
                    e,
                )
                return None
            except Exception as e:
                logger.warning(
                    "resolve_fk_value: Django lookup failed for %s model=%s pk=%s: %s",
                    field_name,
                    model_path,
                    fk_id,
                    e,
                )
                return None

        # gRPC service lookup
        if getattr(config, "service", None):
            service = cast(str, config.service)
            get_method = getattr(config, "get_method", "get")
            # Use the FK target resource class when configured, otherwise fall back
            # to the row resource class for backward compatibility.
            related_resource_class = getattr(config, "resource_class", None) or self._resource_class
            try:
                adapter = self._get_fk_adapter(service)
                if adapter is None:
                    logger.warning(
                        "resolve_fk_value: No adapter for service=%s field=%s",
                        service,
                        field_name,
                    )
                    return None
                result = self._adapter_get(adapter, related_resource_class, str(fk_id), get_method)
                if result is None:
                    return None
                return str(getattr(result, config.display_field, str(result)))
            except Exception as e:
                logger.warning(
                    "resolve_fk_value: gRPC lookup failed for %s service=%s pk=%s: %s",
                    field_name,
                    service,
                    fk_id,
                    e,
                )
                return None

        return str(fk_id) if fk_id is not None else None

    # ── Object retrieval ───────────────────────────────────────────────────

    def get_object(
        self,
        request: HttpRequest,
        object_id: str,
        from_field: str | None = None,
    ) -> ModelWrapper | None:
        return self.fetch_one(str(object_id), request=request)

    # ── Views ──────────────────────────────────────────────────────────────

    def changelist_view(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse:
        extra_context = extra_context or {}
        action = "change" if self._can_update() or self._can_delete() else "view"
        extra_context["title"] = f"Select {self._fake_model._meta.verbose_name} to {action}"
        response = super().changelist_view(request, extra_context)
        if self.grpc_cursor_pagination:
            if not hasattr(response, "context_data"):
                return response  # type: ignore[return-value]
            cl = response.context_data.get("cl")
            if cl and hasattr(cl, "cursor_next_url"):
                response.context_data["cursor_next_url"] = cl.cursor_next_url
        return response  # type: ignore[return-value]

    def add_view(
        self,
        request: HttpRequest,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_add_permission(request):
            raise PermissionDenied

        form_class = self._build_form_class()
        if request.method == "POST":
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    adapter = self.get_adapter()
                    if adapter is None:
                        messages.error(request, "gRPC adapter not available.")
                        return HttpResponseRedirect(
                            reverse(
                                f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                            )
                        )
                    cleaned_data = self.clean_grpc_data(form.cleaned_data)
                    self._adapter_create(
                        adapter,
                        self._resource_class,
                        self.get_grpc_create_data(cleaned_data),
                    )
                    messages.success(
                        request,
                        f"Successfully created {self._fake_model._meta.verbose_name}.",
                    )
                    return HttpResponseRedirect(
                        reverse(
                            f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                        )
                    )
                except GrpcAdminError as exc:
                    logger.exception("Error creating via gRPC: %s", exc)
                    level, message = get_grpc_error_message(exc)
                    messages.add_message(request, level, message)
                except Exception as exc:
                    logger.exception("Error creating via gRPC: %s", exc)
                    messages.error(request, f"Error creating: {exc}")
        else:
            form = form_class()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Add {self._fake_model._meta.verbose_name}",
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "original": None,
            "object_id": None,
            "form": form,
            "detail_rows": [],
            "add": True,
            "change": False,
            "can_edit": True,
            "can_delete": False,
            "has_add_permission": True,
            "has_change_permission": False,
            "has_delete_permission": False,
            "has_view_permission": True,
            "has_editable_inline_admin_formsets": False,
            "inline_admin_formsets": [],
            "errors": [],
            "is_popup": False,
            "save_as": False,
            "show_save": True,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
            "show_delete_link": False,
            "media": self.media + form.media,
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            getattr(self, "grpc_add_form_template", None) or self._get_change_form_template(),
            context,
        )

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_view_permission(request):
            raise PermissionDenied

        obj = self.get_object(request, object_id)
        if obj is None:
            return cast(
                HttpResponseRedirect,
                self._get_obj_does_not_exist_redirect(  # type: ignore[attr-defined]
                    request, self._fake_model._meta, object_id
                ),
            )

        can_edit = self._can_update()
        can_delete = self._can_delete()
        form = None

        if request.method == "POST":
            if not can_edit:
                raise PermissionDenied
            form_class = self._build_form_class()
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    adapter = self.get_adapter()
                    if adapter is None:
                        messages.error(request, "gRPC adapter not available.")
                        return HttpResponseRedirect(request.path)
                    cleaned_data = self.clean_grpc_data(form.cleaned_data)
                    self._adapter_update(
                        adapter,
                        self._resource_class,
                        str(obj.pk),
                        self.get_grpc_update_data(obj, cleaned_data),
                    )
                    messages.success(
                        request,
                        f"Successfully updated {self._fake_model._meta.verbose_name}.",
                    )
                    return HttpResponseRedirect(request.path)
                except GrpcAdminError as exc:
                    logger.exception("Error updating via gRPC: %s", exc)
                    level, message = get_grpc_error_message(exc)
                    messages.add_message(request, level, message)
                except Exception as exc:
                    logger.exception("Error updating via gRPC: %s", exc)
                    messages.error(request, f"Error updating: {exc}")
        elif can_edit:
            form_class = self._build_form_class()
            form = form_class(initial=self.get_grpc_form_initial(obj))

        context = {
            **self.admin_site.each_context(request),
            "title": f"{self._fake_model._meta.verbose_name}: {obj}",
            "original": obj,
            "object_id": object_id,
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "form": form,
            "detail_rows": self.get_grpc_detail_rows(obj),
            "add": False,
            "change": True,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": can_edit,
            "has_delete_permission": can_delete,
            "has_view_permission": True,
            "has_editable_inline_admin_formsets": False,
            "inline_admin_formsets": [],
            "errors": [],
            "is_popup": False,
            "save_as": False,
            "show_save": can_edit,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
            "show_delete_link": can_delete,
            "media": self.media + (form.media if form else self.media.__class__()),
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            self._get_change_form_template(),
            context,
        )

    def _changelist_redirect(self, request: HttpRequest) -> HttpResponseRedirect:
        """Redirect to the changelist, falling back to the request path on reversal errors."""
        try:
            url = reverse(
                f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
            )
        except NoReverseMatch:
            url = request.headers.get("Referer") or request.path
        return HttpResponseRedirect(url)

    def delete_view(
        self,
        request: HttpRequest,
        object_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_delete_permission(request):
            raise PermissionDenied

        obj = self.get_object(request, object_id)
        if obj is None:
            return cast(
                HttpResponseRedirect,
                self._get_obj_does_not_exist_redirect(  # type: ignore[attr-defined]
                    request, self._fake_model._meta, object_id
                ),
            )

        if request.method == "POST":
            try:
                adapter = self.get_adapter()
                if adapter is None:
                    messages.error(request, "gRPC adapter not available.")
                    return self._changelist_redirect(request)
                deleted = self._adapter_delete(adapter, self._resource_class, str(obj.pk))
                if deleted:
                    messages.success(
                        request,
                        f"Successfully deleted {self._fake_model._meta.verbose_name} '{obj}'.",
                    )
                else:
                    messages.warning(
                        request,
                        f"Delete returned False for {self._fake_model._meta.verbose_name} '{obj}'.",
                    )
            except GrpcAdminError as exc:
                logger.exception("Error deleting via gRPC: %s", exc)
                level, message = get_grpc_error_message(exc)
                messages.add_message(request, level, message)
            except Exception as exc:
                logger.exception("Error deleting via gRPC: %s", exc)
                messages.error(request, f"Error deleting: {exc}")
            return self._changelist_redirect(request)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Delete {self._fake_model._meta.verbose_name}",
            "original": obj,
            "object_id": object_id,
            "object_name": str(self._fake_model._meta.verbose_name),
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "has_delete_permission": True,
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            getattr(self, "grpc_delete_template", None) or self._get_delete_confirm_template(),
            context,
        )


def run_async(coro: Any) -> Any:
    """
    Run a coroutine from synchronous code.

    All coroutines are dispatched to a single, persistent background event loop.
    This keeps ``grpc.aio.Channel`` instances bound to one loop even when the
    synchronous Django admin makes multiple adapter calls, and avoids creating a
    fresh thread/loop for every call.

    Args:
        coro: A coroutine object (not a coroutine function).

    Returns:
        The awaitable's result.
    """
    if not asyncio.iscoroutine(coro):
        raise TypeError("run_async expects a coroutine object")
    return _async_bridge.run(coro)


class _AsyncBridge:
    """Persistent background event loop for running coroutines from sync code."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
                and self._loop is not None
                and not self._loop.is_closed()
            ):
                return self._loop

            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever,
                daemon=True,
                name="django-admin-grpc-async-bridge",
            )
            self._thread.start()
            return self._loop

    def run(self, coro: Any) -> Any:
        loop = self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result()
        except Exception:
            # Unwrap cancellation exceptions raised by the bridge so callers see
            # the underlying error raised inside the coroutine.
            future.cancel()
            raise

    def close(self) -> None:
        with self._lock:
            thread = self._thread
            loop = self._loop
            self._thread = None
            self._loop = None

        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                logger.exception("Error stopping async bridge loop")
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        if loop is not None and not loop.is_closed():
            try:
                loop.close()
            except Exception:
                logger.exception("Error closing async bridge loop")


_async_bridge = _AsyncBridge()
atexit.register(_async_bridge.close)


class AsyncGrpcResourceAdmin(GrpcResourceAdmin):
    """
    ``GrpcResourceAdmin`` variant that supports async adapters.

    When the resolved adapter is a ``BaseAsyncGrpcServiceAdapter``, list/get/
    create/update/delete calls are automatically run via ``run_async`` so the admin
    views remain ordinary synchronous Django views.  For ASGI deployments, the
    ``async_changelist_view`` method provides an async-native entry point.
    """

    def get_adapter(self) -> BaseGrpcServiceAdapter | BaseAsyncGrpcServiceAdapter | None:
        """Return the gRPC adapter, consulting the async registry as a fallback."""
        adapter = super().get_adapter()
        if adapter is not None:
            return adapter
        if self.service_name and self._adapter is None:
            from django_admin_grpc.async_adapter import async_adapter_registry

            self._adapter = async_adapter_registry.get_adapter(self.service_name)
        return self._adapter

    def _is_async_adapter(self) -> bool:
        adapter = self.get_adapter()
        return isinstance(adapter, BaseAsyncGrpcServiceAdapter)

    async def async_changelist_view(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> Any:
        """
        Async-native changelist view for ASGI deployments.

        This delegates to the synchronous ``changelist_view`` (which in turn
        uses ``fetch_list``).  ``fetch_list`` detects async adapters and runs
        the adapter's ``list()`` coroutine through ``run_async`` automatically.
        """
        from asgiref.sync import sync_to_async

        return await sync_to_async(self.changelist_view)(request, extra_context=extra_context)
