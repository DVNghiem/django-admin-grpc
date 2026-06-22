"""
Tests for django_admin_grpc.audit.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import GrpcResourceAdmin
from django_admin_grpc.audit import (
    AuditEvent,
    BaseAuditBackend,
    CompositeAuditBackend,
    DjangoModelAuditBackend,
    LoggingAuditBackend,
    load_audit_backend,
)
from django_admin_grpc.models import GrpcAuditLog
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import BaseGrpcResource, CharFieldConfig, IntegerFieldConfig


class ItemResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "item"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class MemoryBackend(BaseAuditBackend):
    def __init__(self):
        self.events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        self.events.append(event)

    def query(self, **filters) -> list[AuditEvent]:
        result = self.events
        if "operation" in filters:
            result = [e for e in result if e.operation == filters["operation"]]
        if "success" in filters:
            result = [e for e in result if e.success == filters["success"]]
        return result


class MockAdapter(BaseGrpcServiceAdapter):
    service_name = "items"

    def __init__(self, items=None):
        self._items = list(items or [])
        self.calls: list[tuple[str, tuple]] = []

    def list(self, resource_class, page=1, page_size=25, filters=None, request=None):
        return PagedResult(items=self._items, total=len(self._items))

    def get(self, resource_class, pk, request=None):
        for item in self._items:
            if str(item.pk) == str(pk):
                return item
        return None

    def create(self, resource_class, data, request=None):
        self.calls.append(("create", data))
        return ItemResource(id=99, name=data.get("name"))

    def update(self, resource_class, pk, data, request=None):
        self.calls.append(("update", pk, data))
        return ItemResource(id=pk, name=data.get("name"))

    def delete(self, resource_class, pk, request=None):
        self.calls.append(("delete", pk))
        return True


class ItemAdmin(GrpcResourceAdmin):
    resource_class = ItemResource
    adapter_class = MockAdapter
    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name"]


def _request(user=None, data=None):
    request = RequestFactory().post("/", data or {})
    request.session = {}  # type: ignore[attr-defined]
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    request.user = user or AnonymousUser()
    return request


class TestAuditEvent:
    def test_fields(self):
        event = AuditEvent(
            resource_name="Item",
            operation="create",
            pk=1,
            user="alice",
            timestamp=datetime.now(UTC),
            before={},
            after={"id": 1},
            diff={"id": 1},
            success=True,
            error=None,
            request_id="r-1",
            extra={"ip": "127.0.0.1"},
        )
        assert event.resource_name == "Item"
        assert event.operation == "create"


class TestLoggingAuditBackend:
    def test_log_outputs_json(self, caplog):
        backend = LoggingAuditBackend()
        event = AuditEvent(
            resource_name="Item",
            operation="update",
            pk="1",
            user="bob",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            before={"name": "a"},
            after={"name": "b"},
            diff={"name": {"before": "a", "after": "b"}},
            success=True,
            error=None,
            request_id="r-2",
            extra=None,
        )
        with caplog.at_level(logging.INFO, logger="django_admin_grpc.audit"):
            backend.log(event)
        assert len(caplog.records) == 1
        payload = json.loads(caplog.records[0].message)
        assert payload["resource_name"] == "Item"
        assert payload["user"] == "bob"


@pytest.mark.django_db
class TestDjangoModelAuditBackend:
    def test_log_and_query(self):
        backend = DjangoModelAuditBackend()
        event = AuditEvent(
            resource_name="Item",
            operation="delete",
            pk="7",
            user="carol",
            timestamp=datetime.now(UTC),
            before={"id": 7},
            after=None,
            diff=None,
            success=False,
            error="not found",
            request_id="r-3",
            extra={"path": "/admin/"},
        )
        backend.log(event)
        rows = backend.query(operation="delete")
        assert len(rows) == 1
        assert rows[0].pk == "7"
        assert rows[0].success is False


class TestCompositeAuditBackend:
    def test_fans_out_and_queries(self):
        b1 = MemoryBackend()
        b2 = MemoryBackend()
        composite = CompositeAuditBackend([b1, b2])
        event = AuditEvent(
            resource_name="Item",
            operation="create",
            pk=1,
            user="dave",
            timestamp=datetime.now(UTC),
            before={},
            after={"id": 1},
            diff={"id": 1},
            success=True,
            error=None,
            request_id="r-4",
            extra=None,
        )
        composite.log(event)
        assert len(b1.events) == 1
        assert len(b2.events) == 1
        assert len(composite.query(operation="create")) == 1


class TestLoadAuditBackend:
    def test_default_returns_logging_backend(self):
        backend = load_audit_backend()
        assert isinstance(backend, LoggingAuditBackend)

    def test_loads_dotted_path(self, settings):
        backend = load_audit_backend("django_admin_grpc.audit.DjangoModelAuditBackend")
        assert isinstance(backend, DjangoModelAuditBackend)


class TestAuditMixin:
    def test_create_logs_success(self):
        backend = MemoryBackend()

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request(data={"name": "Widget"})
        admin.add_view(request)
        creates = [e for e in backend.events if e.operation == "create"]
        assert len(creates) == 1
        assert creates[0].success is True
        assert creates[0].user is None  # AnonymousUser has no get_username

    def test_update_logs_before_and_after(self):
        backend = MemoryBackend()
        adapter = MockAdapter([ItemResource(id=1, name="old")])

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            adapter_class = adapter

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request(data={"name": "new-name"})
        admin.change_view(request, "1")
        updates = [e for e in backend.events if e.operation == "update"]
        assert len(updates) == 1
        assert updates[0].before == {"id": 1, "name": "old"}
        assert updates[0].after == {"id": "1", "name": "new-name"}

    def test_failed_delete_logs_error(self):
        backend = MemoryBackend()

        class FailingAdapter(BaseGrpcServiceAdapter):
            service_name = "items"

            def list(self, resource_class, page=1, page_size=25, filters=None, request=None):
                return PagedResult(items=[])

            def get(self, resource_class, pk, request=None):
                return ItemResource(id=1, name="x")

            def delete(self, resource_class, pk, request=None):
                raise RuntimeError("boom")

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            adapter_class = FailingAdapter

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request()
        response = admin.delete_view(request, "1")
        assert response.status_code == 302
        deletes = [e for e in backend.events if e.operation == "delete"]
        assert len(deletes) == 1
        assert deletes[0].success is False
        assert "boom" in (deletes[0].error or "")

    def test_create_event_before_is_none(self):
        backend = MemoryBackend()

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request(data={"name": "Widget"})
        admin.add_view(request)
        creates = [e for e in backend.events if e.operation == "create"]
        assert len(creates) == 1
        assert creates[0].before is None

    def test_bulk_create_action_logs_aggregate_event(self):
        backend = MemoryBackend()

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            grpc_bulk_create_enabled = True
            actions = ["bulk_create_action"]

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request()
        request.POST = {"_selected_action": ["1", "2"]}
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        admin.bulk_create_action(request, qs)
        events = [e for e in backend.events if e.operation == "bulk_create"]
        assert len(events) == 1
        assert events[0].success is True
        assert events[0].before is None
        assert isinstance(events[0].after, list)
        assert len(events[0].after) == 2

    def test_bulk_update_action_logs_aggregate_event(self):
        backend = MemoryBackend()
        adapter = MockAdapter([ItemResource(id=1, name="old-1"), ItemResource(id=2, name="old-2")])

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            adapter_class = adapter
            grpc_bulk_update_enabled = True
            actions = ["bulk_update_action"]

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request()
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        admin.bulk_update_action(request, qs)
        events = [e for e in backend.events if e.operation == "bulk_update"]
        assert len(events) == 1
        assert events[0].success is True
        assert isinstance(events[0].before, list)
        assert len(events[0].before) == 2
        assert isinstance(events[0].after, list)
        assert len(events[0].after) == 2

    def test_apply_grpc_bulk_delete_logs_aggregate_event(self):
        backend = MemoryBackend()
        adapter = MockAdapter([ItemResource(id=1, name="x"), ItemResource(id=2, name="y")])

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            adapter_class = adapter
            grpc_enable_delete = True

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request()
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        admin.apply_grpc_bulk_delete(request, qs)
        events = [e for e in backend.events if e.operation == "bulk_delete"]
        assert len(events) == 1
        assert events[0].success is True
        assert isinstance(events[0].before, list)
        assert len(events[0].before) == 2
        assert events[0].after == {"deleted": 2}

    def test_apply_grpc_bulk_update_emits_audit_event(self):
        """Regression test: AuditMixin super() chain reaches apply_grpc_bulk_update."""
        backend = MemoryBackend()
        adapter = MockAdapter(
            [ItemResource(id=1, name="old-1"), ItemResource(id=2, name="old-2")]
        )

        class AuditedAdmin(ItemAdmin):
            audit_backend = backend
            adapter_class = adapter
            grpc_enable_update = True

        admin = AuditedAdmin(admin_site=AdminSite())
        request = _request()
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        updated, errors = admin.apply_grpc_bulk_update(request, qs, {"name": "new-name"})

        assert updated == 2
        assert errors == 0
        events = [e for e in backend.events if e.operation == "update"]
        assert len(events) == 2
        assert all(e.success for e in events)
        assert {e.pk for e in events} == {"1", "2"}


class TestGrpcAuditLogModel:
    @pytest.mark.django_db
    def test_to_audit_event(self):
        log = GrpcAuditLog.objects.create(
            resource_name="Item",
            operation="create",
            pk_value="5",
            user="alice",
            timestamp=datetime.now(UTC),
            before={},
            after={"id": 5},
            success=True,
        )
        event = log.to_audit_event()
        assert event.pk == "5"
        assert event.operation == "create"
