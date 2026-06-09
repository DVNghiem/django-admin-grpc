"""
Tests for django_admin_grpc.admin module.
"""
from unittest.mock import Mock, patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import GrpcChangeList, GrpcResourceAdmin, grpc_action
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FKFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
)


class ProductResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "product"
        verbose_name = "Product"
        verbose_name_plural = "Products"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
        FloatFieldConfig(name="price"),
        BooleanFieldConfig(name="active"),
    ]


class MockAdapter(BaseGrpcServiceAdapter):
    service_name = "products"

    def __init__(self, items=None):
        self._items = items or []

    def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(
            items=self._items,
            total=len(self._items),
            page=page,
            page_size=page_size,
        )

    def get(self, resource_class, pk):
        for item in self._items:
            if str(item.pk) == str(pk):
                return item
        return None

    def create(self, resource_class, data):
        return ProductResource(**data)

    def update(self, resource_class, pk, data):
        return ProductResource(id=pk, **data)

    def delete(self, resource_class, pk):
        return True


class ProductAdmin(GrpcResourceAdmin):
    resource_class = ProductResource
    service_name = "products"
    grpc_filter_config = ["name", "active"]
    grpc_form_fields = ["name", "price", "active"]
    grpc_enable_create = True
    grpc_enable_delete = True


class NoCreateAdmin(GrpcResourceAdmin):
    resource_class = ProductResource
    adapter_class = MockAdapter
    grpc_enable_create = False
    grpc_enable_delete = False


@pytest.fixture
def admin_instance():
    return ProductAdmin(admin_site=AdminSite())


@pytest.fixture
def no_create_admin():
    return NoCreateAdmin(admin_site=AdminSite())


@pytest.fixture
def request_factory():
    return RequestFactory()


class TestGrpcResourceAdminInit:
    def test_requires_resource_class(self):
        class BadAdmin(GrpcResourceAdmin):
            pass

        with pytest.raises(ValueError, match="must define resource_class"):
            BadAdmin(admin_site=AdminSite())

    def test_sets_fake_model(self, admin_instance):
        assert admin_instance._fake_model is not None
        assert admin_instance._fake_model._meta.model_name == "product"


class TestGrpcResourceAdminGetObject:
    def test_get_object_found(self, admin_instance, reset_registry):
        product = ProductResource(id=1, name="Widget", price=10.0, active=True)
        adapter = MockAdapter([product])
        reset_registry.register("products", adapter)

        request = RequestFactory().get("/")
        obj = admin_instance.get_object(request, "1")
        assert obj is not None
        assert obj.pk == 1
        assert obj.name == "Widget"

    def test_get_object_not_found(self, admin_instance, reset_registry):
        reset_registry.register("products", MockAdapter([]))
        request = RequestFactory().get("/")
        obj = admin_instance.get_object(request, "999")
        assert obj is None

    def test_get_object_no_adapter(self, no_create_admin):
        request = RequestFactory().get("/")
        obj = no_create_admin.get_object(request, "1")
        assert obj is None


class TestGrpcResourceAdminFetchList:
    def test_fetch_list_with_adapter(self, admin_instance, reset_registry):
        product = ProductResource(id=1, name="Widget", price=10.0, active=True)
        adapter = MockAdapter([product])
        reset_registry.register("products", adapter)

        result = admin_instance.fetch_list(page=1, page_size=25)
        assert isinstance(result, PagedResult)
        assert len(result.items) == 1

    def test_fetch_list_no_adapter(self):
        class NoAdapterAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            service_name = "missing"

        admin = NoAdapterAdmin(admin_site=AdminSite())
        result = admin.fetch_list()
        assert isinstance(result, PagedResult)
        assert result.items == []

    def test_fetch_list_with_cursor_pagination(self, reset_registry):
        class CursorAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            service_name = "products"
            grpc_cursor_pagination = True

        admin = CursorAdmin(admin_site=AdminSite())
        product = ProductResource(id=1, name="Widget")
        adapter = MockAdapter([product])
        reset_registry.register("products", adapter)

        result = admin.fetch_list(page=1, page_size=10)
        assert isinstance(result, PagedResult)


class TestGrpcResourceAdminPermissions:
    def test_has_add_permission_true(self, admin_instance, reset_registry):
        reset_registry.register("products", MockAdapter())
        request = RequestFactory().get("/")
        assert admin_instance.has_add_permission(request) is True

    def test_has_add_permission_false_no_enable(self, no_create_admin):
        request = RequestFactory().get("/")
        assert no_create_admin.has_add_permission(request) is False

    def test_has_add_permission_false_no_adapter(self, admin_instance):
        request = RequestFactory().get("/")
        # No adapter registered
        assert admin_instance.has_add_permission(request) is False

    def test_has_delete_permission_true(self, admin_instance, reset_registry):
        reset_registry.register("products", MockAdapter())
        request = RequestFactory().get("/")
        assert admin_instance.has_delete_permission(request) is True

    def test_has_delete_permission_false(self, no_create_admin):
        request = RequestFactory().get("/")
        assert no_create_admin.has_delete_permission(request) is False

    def test_has_view_permission(self, admin_instance):
        request = RequestFactory().get("/")
        assert admin_instance.has_view_permission(request) is True

    def test_has_change_permission_delegates_to_view(self, admin_instance):
        request = RequestFactory().get("/")
        assert admin_instance.has_change_permission(request) is True

    def test_grpc_permission_hooks_can_deny_actions(self, reset_registry):
        class HookAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_form_fields = ["name"]
            grpc_enable_create = True
            grpc_enable_delete = True

            def has_grpc_add_permission(self, request):
                return False

            def has_grpc_delete_permission(self, request, obj=None):
                return False

            def has_grpc_view_permission(self, request, obj=None):
                return False

        admin = HookAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        assert admin.has_add_permission(request) is False
        assert admin.has_delete_permission(request) is False
        assert admin.has_view_permission(request) is False

    def test_grpc_change_permission_hook_can_deny_change(self):
        class HookAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter

            def has_grpc_change_permission(self, request, obj=None):
                return False

        admin = HookAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        assert admin.has_change_permission(request) is False


class TestGrpcResourceAdminGetGrpcFilters:
    def test_get_grpc_filters(self, admin_instance):
        request = RequestFactory().get("/?name=Widget&active=1&p=1")
        filters = admin_instance.get_grpc_filters(request)
        assert filters == {"name": "Widget", "active": "1"}

    def test_get_grpc_filters_excludes_pagination(self, admin_instance):
        request = RequestFactory().get("/?p=2&o=name")
        filters = admin_instance.get_grpc_filters(request)
        assert filters == {}

    def test_get_grpc_filters_with_dict_config(self):
        class DictConfigAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {"name": {"type": "text"}, "active": {"type": "boolean"}}

        admin = DictConfigAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?name=Widget&extra=1")
        filters = admin.get_grpc_filters(request)
        assert "name" in filters
        assert "extra" not in filters

    def test_get_grpc_filters_with_list_config(self, admin_instance):
        request = RequestFactory().get("/?name=Widget&extra=1")
        filters = admin_instance.get_grpc_filters(request)
        assert "name" in filters
        assert "extra" not in filters

    def test_get_grpc_filters_no_config(self):
        class NoFilterAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {}

        admin = NoFilterAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?name=Widget")
        filters = admin.get_grpc_filters(request)
        assert filters == {}

    def test_numeric_range_params_pass_through(self):
        class RangeAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {"price": {"type": "number_range"}}

        admin = RangeAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?price__gte=10&price__lte=100")
        filters = admin.get_grpc_filters(request)
        assert filters == {"price__gte": "10", "price__lte": "100"}

    def test_date_range_params_pass_through(self):
        class DateAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {"created_at": {"type": "date_range"}}

        admin = DateAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?created_at__gte=2024-01-01&created_at__lte=2024-12-31")
        filters = admin.get_grpc_filters(request)
        assert filters == {"created_at__gte": "2024-01-01", "created_at__lte": "2024-12-31"}

    def test_multi_choices_comma_separated(self):
        class MultiAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {
                "status": {
                    "type": "multi_choices",
                    "choices": [("active", "Active"), ("pending", "Pending")],
                }
            }

        admin = MultiAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?status=active,pending")
        filters = admin.get_grpc_filters(request)
        assert filters == {"status": ["active", "pending"]}

    def test_multi_choices_repeated_params(self):
        class MultiAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_filter_config = {
                "status": {
                    "type": "multi_choices",
                    "choices": [("active", "Active"), ("pending", "Pending")],
                }
            }

        admin = MultiAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/?status=active&status=pending")
        filters = admin.get_grpc_filters(request)
        assert filters == {"status": ["active", "pending"]}

    def test_existing_simple_filters_still_work(self, admin_instance):
        request = RequestFactory().get("/?name=Widget&active=1&p=1")
        filters = admin_instance.get_grpc_filters(request)
        assert filters == {"name": "Widget", "active": "1"}


class TestGrpcResourceAdminBuildFormClass:
    def test_build_form_class(self, admin_instance):
        form_class = admin_instance._build_form_class()
        assert "name" in form_class.base_fields
        assert "price" in form_class.base_fields
        assert "active" in form_class.base_fields

    def test_build_form_class_excludes_readonly_and_detail_only_fields(self):
        class FieldControlResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "fieldcontrol"

            fields = [
                CharFieldConfig(name="name"),
                CharFieldConfig(name="server_code", readonly=True),
                CharFieldConfig(name="audit_note", detail_only=True),
                CharFieldConfig(name="list_badge", list_only=True),
            ]

        class FieldControlAdmin(GrpcResourceAdmin):
            resource_class = FieldControlResource
            adapter_class = MockAdapter
            grpc_form_fields = ["name", "server_code", "audit_note", "list_badge"]

        admin = FieldControlAdmin(admin_site=AdminSite())
        form_class = admin._build_form_class()
        assert list(form_class.base_fields) == ["name"]


class TestGrpcResourceAdminValidation:
    def test_clean_grpc_data_applies_field_and_object_hooks(self):
        class ValidationAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter

            def clean_name(self, value):
                return value.strip()

            def clean(self, data):
                cleaned = dict(data)
                cleaned["name"] = cleaned["name"].upper()
                cleaned["validated"] = True
                return cleaned

        admin = ValidationAdmin(admin_site=AdminSite())
        data = admin.clean_grpc_data({"name": " widget "})
        assert data == {"name": "WIDGET", "validated": True}

    def test_clean_grpc_data_can_raise_validation_error(self):
        from django import forms

        class ValidationAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter

            def clean_name(self, value):
                raise forms.ValidationError("Invalid name")

        admin = ValidationAdmin(admin_site=AdminSite())
        with pytest.raises(forms.ValidationError):
            admin.clean_grpc_data({"name": "bad"})


class TestGrpcResourceAdminDetailFields:
    def test_get_grpc_detail_fields_default(self, admin_instance):
        fields = admin_instance.get_grpc_detail_fields()
        assert fields == [
            ("Id", "id"),
            ("Name", "name"),
            ("Price", "price"),
            ("Active", "active"),
        ]

    def test_get_grpc_detail_fields_custom(self, admin_instance):
        admin_instance.grpc_detail_fields = ["name", "price"]
        fields = admin_instance.get_grpc_detail_fields()
        assert fields == [("Name", "name"), ("Price", "price")]

    def test_get_grpc_detail_fields_with_labels(self, admin_instance):
        admin_instance.grpc_detail_fields = [
            ("Product Name", "name"),
            ("Cost", "price"),
        ]
        fields = admin_instance.get_grpc_detail_fields()
        assert fields == [("Product Name", "name"), ("Cost", "price")]

    def test_get_grpc_detail_fields_excludes_list_only(self):
        class DetailControlResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "detailcontrol"

            fields = [
                CharFieldConfig(name="name"),
                CharFieldConfig(name="badge", list_only=True),
                CharFieldConfig(name="note", detail_only=True),
            ]

        class DetailControlAdmin(GrpcResourceAdmin):
            resource_class = DetailControlResource
            adapter_class = MockAdapter

        admin = DetailControlAdmin(admin_site=AdminSite())
        assert admin.get_grpc_detail_fields() == [("Name", "name"), ("Note", "note")]


class TestGrpcResourceAdminAdapter:
    def test_get_adapter_from_class(self, no_create_admin):
        adapter = no_create_admin.get_adapter()
        assert isinstance(adapter, MockAdapter)

    def test_get_adapter_from_instance(self):
        instance = MockAdapter()

        class InstanceAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = instance

        admin = InstanceAdmin(admin_site=AdminSite())
        assert admin.get_adapter() is instance

    def test_get_adapter_from_registry(self, admin_instance, reset_registry):
        adapter = MockAdapter()
        reset_registry.register("products", adapter)
        assert admin_instance.get_adapter() is adapter

    def test_get_adapter_none(self):
        class NoServiceAdmin(GrpcResourceAdmin):
            resource_class = ProductResource

        admin = NoServiceAdmin(admin_site=AdminSite())
        assert admin.get_adapter() is None


class TestGrpcResourceAdminActions:
    def test_get_actions_no_delete(self, no_create_admin):
        request = RequestFactory().get("/")
        actions = no_create_admin.get_actions(request)
        assert "delete_selected" not in actions
        assert "grpc_delete_selected" not in actions

    def test_get_actions_with_delete(self, admin_instance, reset_registry):
        reset_registry.register("products", MockAdapter())
        request = RequestFactory().get("/")
        actions = admin_instance.get_actions(request)
        assert "grpc_delete_selected" in actions

    def test_get_actions_removes_builtin_delete(self, admin_instance, reset_registry):
        reset_registry.register("products", MockAdapter())
        request = RequestFactory().get("/")
        actions = admin_instance.get_actions(request)
        assert "delete_selected" not in actions

    def test_apply_grpc_bulk_update_updates_selected_pks(self):
        class UpdateAdapter(MockAdapter):
            def __init__(self):
                super().__init__()
                self.updated = []

            def update(self, resource_class, pk, data):
                self.updated.append((pk, data))
                return ProductResource(id=pk, **data)

        adapter = UpdateAdapter()

        class UpdateAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = adapter

        admin = UpdateAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        updated, errors = admin.apply_grpc_bulk_update(request, qs, {"active": True})

        assert updated == 2
        assert errors == 0
        assert adapter.updated == [("1", {"active": True}), ("2", {"active": True})]


class TestGrpcChangeList:
    def test_init(self, admin_instance):
        request = RequestFactory().get("/")
        cl = GrpcChangeList(
            request=request,
            model=admin_instance.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin_instance,
            sortable_by=["name"],
            search_help_text="",
        )
        assert cl._grpc_model_admin is admin_instance

    def test_get_queryset(self, admin_instance):
        request = RequestFactory().get("/")
        cl = GrpcChangeList(
            request=request,
            model=admin_instance.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin_instance,
            sortable_by=["name"],
            search_help_text="",
        )
        assert cl.get_queryset(request) == []

    def test_get_results(self, admin_instance, reset_registry):
        product = ProductResource(id=1, name="Widget", price=10.0, active=True)
        adapter = MockAdapter([product])
        reset_registry.register("products", adapter)

        request = RequestFactory().get("/")
        cl = GrpcChangeList(
            request=request,
            model=admin_instance.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin_instance,
            sortable_by=["name"],
            search_help_text="",
        )
        cl.get_results(request)
        assert len(cl.result_list) == 1
        assert cl.result_count == 1
        assert cl.multi_page is False

    def test_get_results_with_error(self, admin_instance):
        request = RequestFactory().get("/")
        cl = GrpcChangeList(
            request=request,
            model=admin_instance.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin_instance,
            sortable_by=["name"],
            search_help_text="",
        )
        cl.get_results(request)
        assert cl.result_list == []
        assert cl.result_count == 0

    def test_get_results_with_search(self, admin_instance, reset_registry):
        product = ProductResource(id=1, name="Widget")
        adapter = MockAdapter([product])
        reset_registry.register("products", adapter)

        request = RequestFactory().get("/?q=Widget")
        cl = GrpcChangeList(
            request=request,
            model=admin_instance.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=["name"],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin_instance,
            sortable_by=["name"],
            search_help_text="",
        )
        cl.get_results(request)
        assert len(cl.result_list) == 1

    def test_get_results_cursor_pagination(self, reset_registry):
        class CursorAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            service_name = "products"
            grpc_cursor_pagination = True

        admin = CursorAdmin(admin_site=AdminSite())
        adapter = MockAdapter([ProductResource(id=1, name="Widget")])
        reset_registry.register("products", adapter)

        request = RequestFactory().get("/?cursor=abc")
        cl = GrpcChangeList(
            request=request,
            model=admin.model,
            list_display=["name"],
            list_display_links=["name"],
            list_filter=[],
            date_hierarchy=None,
            search_fields=[],
            list_select_related=False,
            list_per_page=25,
            list_max_show_all=200,
            list_editable=[],
            model_admin=admin,
            sortable_by=["name"],
            search_help_text="",
        )
        cl.get_results(request)
        assert cl.result_list is not None


class TestGrpcResourceAdminDetailRows:
    def test_get_grpc_detail_rows(self, admin_instance):
        product = ProductResource(id=1, name="Widget", price=10.0, active=True)
        rows = admin_instance.get_grpc_detail_rows(product)
        assert len(rows) == 4
        assert rows[0]["label"] == "Id"
        assert rows[0]["field_name"] == "id"
        assert rows[0]["value"] == 1
        assert rows[0]["is_boolean"] is False


class TestGrpcResourceAdminResolveFk:
    def test_no_config_returns_fk_id(self, admin_instance):
        assert admin_instance.resolve_fk_value("name", None, 42) == 42

    def test_non_fk_config_returns_fk_id(self, admin_instance):
        config = ProductResource.get_field_config("name")
        assert admin_instance.resolve_fk_value("name", config, 42) == 42

    def test_falsy_fk_id_returns_fk_id(self, admin_instance):
        config = FKFieldConfig(name="category_id", model="auth.User")
        assert admin_instance.resolve_fk_value("category_id", config, "") == ""
        assert admin_instance.resolve_fk_value("category_id", config, None) is None

    def test_invalid_model_path(self, admin_instance):
        config = FKFieldConfig(name="x", model="NoDot")
        assert admin_instance.resolve_fk_value("x", config, 1) == 1

    def test_invalid_model_path_with_display_field_returns_none(self, admin_instance):
        config = FKFieldConfig(name="x", model="NoDot", display_field="name")
        assert admin_instance.resolve_fk_value("x", config, 1) is None

    def test_model_does_not_exist(self, admin_instance):
        config = FKFieldConfig(name="x", model="nonexistent.Model")
        assert admin_instance.resolve_fk_value("x", config, 1) == 1

    def test_model_does_not_exist_with_display_field_returns_none(self, admin_instance):
        config = FKFieldConfig(name="x", model="nonexistent.Model", display_field="name")
        assert admin_instance.resolve_fk_value("x", config, 1) is None

    def test_service_lookup(self, admin_instance, reset_registry):
        class FakeAdapter:
            service_name = "users"
            def get(self, pk):
                obj = Mock()
                obj.name = "Alice"
                return obj

        reset_registry.register("users", FakeAdapter())
        config = FKFieldConfig(name="owner", service="users", display_field="name")
        result = admin_instance.resolve_fk_value("owner", config, "1")
        assert result == "Alice"

    def test_service_lookup_without_display_field_returns_fk_id(self, admin_instance, reset_registry):
        class FakeAdapter:
            service_name = "users"
            def get(self, pk):
                obj = Mock()
                obj.name = "Alice"
                return obj

        reset_registry.register("users", FakeAdapter())
        config = FKFieldConfig(name="owner", service="users")
        result = admin_instance.resolve_fk_value("owner", config, "1")
        assert result == "1"

    def test_model_lookup_without_display_field_returns_fk_id(self, admin_instance):
        config = FKFieldConfig(name="owner", model="auth.User")
        result = admin_instance.resolve_fk_value("owner", config, "1")
        assert result == "1"

    def test_service_lookup_typeerror(self, admin_instance, reset_registry):
        class StrictAdapter:
            service_name = "strict"
            def get(self, pk_id):
                obj = Mock()
                obj.name = "Bob"
                return obj

        reset_registry.register("strict", StrictAdapter())
        config = FKFieldConfig(name="ref", service="strict", display_field="name")
        result = admin_instance.resolve_fk_value("ref", config, "1")
        assert result == "Bob"

    def test_service_no_adapter(self, admin_instance):
        config = FKFieldConfig(name="ref", service="missing")
        result = admin_instance.resolve_fk_value("ref", config, "1")
        assert result == "1"

    def test_service_no_adapter_with_display_field_returns_none(self, admin_instance):
        config = FKFieldConfig(name="ref", service="missing", display_field="name")
        result = admin_instance.resolve_fk_value("ref", config, "1")
        assert result is None


class TestGrpcResourceAdminDeleteSelected:
    def test_delete_selected_success(self, admin_instance, reset_registry):
        adapter = MockAdapter()
        reset_registry.register("products", adapter)
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["1", "2"]

        with patch("django_admin_grpc.admin.messages.success") as mock_success:
            admin_instance._grpc_delete_selected(request, qs)
        mock_success.assert_called_once()

    def test_delete_selected_no_adapter(self):
        class NoAdapterAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            service_name = "missing"

        admin = NoAdapterAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["1"]

        with patch("django_admin_grpc.admin.messages.error") as mock_error:
            admin._grpc_delete_selected(request, qs)
        mock_error.assert_called_once_with(request, "gRPC adapter not available.")

    def test_delete_selected_with_errors(self, admin_instance, reset_registry):
        class BadAdapter(BaseGrpcServiceAdapter):
            service_name = "products"
            def list(self, resource_class, page=1, page_size=25, filters=None):
                return PagedResult(items=[])
            def get(self, resource_class, pk):
                return None
            def delete(self, resource_class, pk):
                raise RuntimeError("boom")

        reset_registry.register("products", BadAdapter())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["1"]

        with patch("django_admin_grpc.admin.messages.error") as mock_error:
            admin_instance._grpc_delete_selected(request, qs)
        mock_error.assert_called_once()


class TestGrpcResourceAdminViews:
    @pytest.fixture
    def view_admin(self, reset_registry):
        class ViewResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "item"
            fields = [
                IntegerFieldConfig(name="id"),
                CharFieldConfig(name="name"),
            ]

        class ViewAdapter(BaseGrpcServiceAdapter):
            service_name = "items"
            def list(self, resource_class, page=1, page_size=25, filters=None):
                return PagedResult(items=[ViewResource(id=1, name="A")], total=1, next_cursor="nxt")
            def get(self, resource_class, pk):
                return ViewResource(id=1, name="A")
            def create(self, resource_class, data):
                return ViewResource(**data)
            def update(self, resource_class, pk, data):
                return ViewResource(id=pk, **data)
            def delete(self, resource_class, pk):
                return True

        class VA(GrpcResourceAdmin):
            resource_class = ViewResource
            service_name = "items"
            grpc_enable_create = True
            grpc_enable_delete = True
            grpc_form_fields = ["name"]
            grpc_cursor_pagination = True

        reset_registry.register("items", ViewAdapter())
        return VA(admin_site=AdminSite())

    def _request(self, method="get", **kwargs):
        req = getattr(RequestFactory(), method)("/", **kwargs)
        req.user = Mock()
        req.user.is_active = True
        req.user.is_staff = True
        return req

    def test_changelist_view(self, view_admin):
        request = self._request()
        with patch("django.contrib.messages.info"):
            response = view_admin.changelist_view(request)
        assert hasattr(response, "context_data")

    def test_add_view_get(self, view_admin):
        request = self._request()
        with patch("django.contrib.messages.success"):
            response = view_admin.add_view(request)
        assert hasattr(response, "context_data")
        assert response.context_data["add"] is True

    def test_change_view_get(self, view_admin):
        request = self._request()
        with patch("django.contrib.messages.success"):
            response = view_admin.change_view(request, "1")
        assert hasattr(response, "context_data")
        assert response.context_data["change"] is True

    def test_delete_view_get(self, view_admin):
        request = self._request()
        response = view_admin.delete_view(request, "1")
        assert hasattr(response, "context_data")
        assert response.context_data["original"] is not None


class TestGrpcResourceAdminWithBase:
    def test_with_base_factory(self):
        class CustomBase:
            custom_attr = True

        new_class = GrpcResourceAdmin.with_base(CustomBase)
        assert issubclass(new_class, GrpcResourceAdmin)
        assert issubclass(new_class, CustomBase)
        assert hasattr(new_class, "custom_attr")

    def test_with_base_name(self):
        class CustomBase:
            pass

        new_class = GrpcResourceAdmin.with_base(CustomBase)
        assert "GrpcResourceAdminWithCustomBase" in new_class.__name__


class TestGrpcResourceAdminTemplateResolution:
    def test_change_form_template_default(self, admin_instance):
        assert admin_instance._get_change_form_template() == "django_admin_grpc/change_form.html"

    def test_delete_confirm_template_default(self, admin_instance):
        assert admin_instance._get_delete_confirm_template() == "django_admin_grpc/delete_confirm.html"

    def test_change_form_template_from_resource_meta(self):
        class TemplResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "templ"
                change_form_template = "custom/change.html"
            fields = [IntegerFieldConfig(name="id")]

        class TemplAdmin(GrpcResourceAdmin):
            resource_class = TemplResource
            adapter_class = MockAdapter

        admin = TemplAdmin(admin_site=AdminSite())
        assert admin._get_change_form_template() == "custom/change.html"

    def test_delete_confirm_template_from_resource_meta(self):
        class TemplResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "templ"
                delete_confirm_template = "custom/delete.html"
            fields = [IntegerFieldConfig(name="id")]

        class TemplAdmin(GrpcResourceAdmin):
            resource_class = TemplResource
            adapter_class = MockAdapter

        admin = TemplAdmin(admin_site=AdminSite())
        assert admin._get_delete_confirm_template() == "custom/delete.html"


class TestGrpcAction:
    def test_decorator_receives_selected_pks(self):
        """Custom @grpc_action receives selected PKs instead of queryset."""
        received_pks = []

        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            actions = ["activate_selected"]

            @grpc_action(description="Activate selected")
            def activate_selected(self, request, selected_pks):
                received_pks.extend(selected_pks)

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["1", "2", "3"]

        # Django's get_actions() returns unbound functions; self is passed explicitly
        action_func = admin.get_actions(request)["activate_selected"][0]
        action_func(admin, request, qs)

        assert received_pks == ["1", "2", "3"]

    def test_decorator_can_call_apply_grpc_bulk_update(self):
        """Custom action can use apply_grpc_bulk_update with selected_pks."""
        class TrackingAdapter(MockAdapter):
            def __init__(self):
                super().__init__()
                self.updated = []

            def update(self, resource_class, pk, data):
                self.updated.append((pk, data))
                return ProductResource(id=pk, **data)

        adapter = TrackingAdapter()

        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = adapter
            actions = ["activate_selected"]

            @grpc_action(description="Activate selected")
            def activate_selected(self, request, selected_pks):
                return self.apply_grpc_bulk_update(request, selected_pks, {"active": True})

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["10", "20"]

        action_func = admin.get_actions(request)["activate_selected"][0]
        updated, errors = action_func(admin, request, qs)

        assert updated == 2
        assert errors == 0
        assert adapter.updated == [("10", {"active": True}), ("20", {"active": True})]

    def test_description_appears_in_get_actions(self):
        """Action description appears in get_actions() tuple."""
        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            actions = ["my_action"]

            @grpc_action(description="My custom action")
            def my_action(self, request, selected_pks):
                pass

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        actions = admin.get_actions(request)

        assert "my_action" in actions
        _func, name, description = actions["my_action"]
        assert name == "my_action"
        assert description == "My custom action"

    def test_default_description_from_method_name(self):
        """Default description is derived from method name if not provided."""
        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            actions = ["do_something_cool"]

            @grpc_action
            def do_something_cool(self, request, selected_pks):
                pass

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        actions = admin.get_actions(request)

        _func, name, description = actions["do_something_cool"]
        assert "do something cool" in description.lower()

    def test_existing_builtin_delete_still_works(self):
        """Built-in grpc_delete_selected continues to work alongside custom actions."""
        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            grpc_enable_delete = True
            actions = ["activate_selected"]

            @grpc_action(description="Activate selected")
            def activate_selected(self, request, selected_pks):
                pass

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        actions = admin.get_actions(request)

        assert "grpc_delete_selected" in actions
        assert "activate_selected" in actions
        assert "delete_selected" not in actions

    def test_permissions_parameter(self):
        """Permissions parameter is forwarded to the action wrapper."""
        class ActionAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = MockAdapter
            actions = ["restricted_action"]

            @grpc_action(description="Restricted", permissions=["change"])
            def restricted_action(self, request, selected_pks):
                pass

        admin = ActionAdmin(admin_site=AdminSite())
        request = RequestFactory().get("/")
        actions = admin.get_actions(request)

        func = actions["restricted_action"][0]
        assert getattr(func, "allowed_permissions", None) == ["change"]

    def test_apply_grpc_bulk_update_accepts_list_directly(self):
        """apply_grpc_bulk_update can receive a list of PKs directly."""
        class TrackingAdapter(MockAdapter):
            def __init__(self):
                super().__init__()
                self.updated = []

            def update(self, resource_class, pk, data):
                self.updated.append(pk)
                return ProductResource(id=pk, **data)

        adapter = TrackingAdapter()

        class BulkAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = adapter

        admin = BulkAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")

        updated, errors = admin.apply_grpc_bulk_update(
            request, ["5", "6"], {"name": "Bulk"}
        )

        assert updated == 2
        assert errors == 0
        assert adapter.updated == ["5", "6"]
