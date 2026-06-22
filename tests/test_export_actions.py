"""
Tests for django_admin_grpc.admin export actions.
"""

from __future__ import annotations

import csv
import io
from unittest.mock import Mock

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import GrpcResourceAdmin
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import BaseGrpcResource, CharFieldConfig, IntegerFieldConfig


class ItemResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "item"
        pk_field = "id"
        verbose_name = "Item"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class PagingAdapter(BaseGrpcServiceAdapter):
    service_name = "items"

    def __init__(self, pages):
        self.pages = pages
        self.list_calls: list[dict] = []

    def list(self, resource_class, page=1, page_size=25, filters=None, request=None):
        self.list_calls.append({"page": page, "page_size": page_size, "filters": filters})
        items = self.pages[page - 1] if page <= len(self.pages) else []
        return PagedResult(items=items, total=sum(len(p) for p in self.pages))

    def get(self, resource_class, pk, request=None):
        return None


class ItemAdmin(GrpcResourceAdmin):
    resource_class = ItemResource
    adapter_class = PagingAdapter
    list_display = ["id", "name"]
    grpc_filter_config = ["name"]


def _request(path="/", data=None, get=None):
    request = RequestFactory().get(path, get or {})
    request.session = {}  # type: ignore[attr-defined]
    return request


class TestExportActions:
    def test_actions_include_export(self):
        admin = ItemAdmin(admin_site=AdminSite())
        request = _request()
        actions = admin.get_actions(request)
        assert "export_as_csv" in actions
        assert "export_as_excel" in actions

    def test_export_csv_streams_all_pages(self):
        pages = [
            [ItemResource(id=1, name="a"), ItemResource(id=2, name="b")],
            [ItemResource(id=3, name="c")],
        ]
        admin = ItemAdmin(admin_site=AdminSite())
        admin._adapter = PagingAdapter(pages)
        request = _request()
        response = admin.export_as_csv(request, Mock())
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(content)))
        assert rows[0] == ["Id", "Name"]
        assert len(rows) == 4  # header + 3 data rows

    def test_export_csv_respects_filters(self):
        pages = [[ItemResource(id=1, name="a")]]
        admin = ItemAdmin(admin_site=AdminSite())
        adapter = PagingAdapter(pages)
        admin._adapter = adapter
        request = _request(get={"name": "a"})
        admin.export_as_csv(request, Mock())
        assert adapter.list_calls[0]["filters"] == {"name": "a"}

    def test_export_csv_limits_max_rows(self):
        pages = [[ItemResource(id=i, name=f"item-{i}")] for i in range(1, 6)]
        admin = ItemAdmin(admin_site=AdminSite())
        admin._adapter = PagingAdapter(pages)
        admin.export_max_rows = 2
        request = _request()
        response = admin.export_as_csv(request, Mock())
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(content)))
        assert len(rows) == 3  # header + 2

    def test_export_csv_custom_fields(self):
        pages = [[ItemResource(id=1, name="a")]]
        admin = ItemAdmin(admin_site=AdminSite())
        admin._adapter = PagingAdapter(pages)
        admin.export_fields = ["name"]
        request = _request()
        response = admin.export_as_csv(request, Mock())
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(content)))
        assert rows[0] == ["Name"]

    def test_export_excel_response(self):
        pages = [[ItemResource(id=1, name="a")]]
        admin = ItemAdmin(admin_site=AdminSite())
        admin._adapter = PagingAdapter(pages)
        request = _request()
        response = admin.export_as_excel(request, Mock())
        assert response.status_code == 200
        assert (
            response["Content-Type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "attachment" in response["Content-Disposition"]

    def test_has_export_permission_override(self):
        class RestrictedAdmin(ItemAdmin):
            def has_export_permission(self, request):
                return False

        admin = RestrictedAdmin(admin_site=AdminSite())
        request = _request()
        response = admin.export_as_csv(request, Mock())
        assert response.status_code == 403

    def test_export_csv_uses_max_page_size_setting(self, settings):
        pages = [[ItemResource(id=i, name=f"item-{i}")] for i in range(1, 3)]
        admin = ItemAdmin(admin_site=AdminSite())
        adapter = PagingAdapter(pages)
        admin._adapter = adapter
        settings.GRPC_ADMIN = {"GRPC_ADMIN_MAX_PAGE_SIZE": 7}
        request = _request()
        admin.export_as_csv(request, Mock())
        assert adapter.list_calls[0]["page_size"] == 7
