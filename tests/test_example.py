"""
Tests validating the example catalog project demonstrates library features.
"""

from unittest.mock import Mock

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from django_admin_grpc.admin import GrpcResourceAdmin, grpc_action
from django_admin_grpc.registry import adapter_registry
from example.catalog.adapters import CatalogGrpcAdapter
from example.catalog.resources import CategoryResource, ProductResource


@pytest.fixture(autouse=True)
def reset_example_adapter():
    """Reset the in-memory example adapter state between tests."""
    adapter_registry.clear()
    CatalogGrpcAdapter._categories = {}
    CatalogGrpcAdapter._products = {}
    CatalogGrpcAdapter._seeded = False
    adapter_registry.register("catalog", CatalogGrpcAdapter())
    adapter_registry.register("catalog_category", CatalogGrpcAdapter())
    yield
    adapter_registry.clear()
    CatalogGrpcAdapter._categories = {}
    CatalogGrpcAdapter._products = {}
    CatalogGrpcAdapter._seeded = False


@pytest.fixture
def adapter():
    return CatalogGrpcAdapter()


class TestExampleResourceFieldControls:
    def test_readonly_id(self):
        fields = {f.name: f for f in ProductResource.get_field_configs()}
        assert fields["id"].readonly is True

    def test_editable_false_on_sku(self):
        fields = {f.name: f for f in ProductResource.get_field_configs()}
        assert fields["sku"].editable is False

    def test_detail_only_notes(self):
        fields = {f.name: f for f in ProductResource.get_field_configs()}
        assert fields["notes"].detail_only is True

    def test_list_only_badge(self):
        fields = {f.name: f for f in ProductResource.get_field_configs()}
        assert fields["badge"].list_only is True


class TestExampleFKChoicesLoader:
    def test_category_id_has_choices_loader(self):
        config = ProductResource.get_field_config("category_id")
        assert config.choices_loader is not None

    def test_choices_loader_returns_categories(self, adapter):
        config = ProductResource.get_field_config("category_id")
        choices = config.choices_loader()
        ids = [c[0] for c in choices]
        assert "cat-1" in ids
        assert "cat-2" in ids


class TestExampleAdapterFiltering:
    def test_number_range_filter(self, adapter):
        result = adapter.list(ProductResource, filters={"price__gte": 100})
        for item in result.items:
            assert item.price >= 100

    def test_date_range_filter(self, adapter):
        result = adapter.list(ProductResource, filters={"release_date__gte": "2023-01-01"})
        for item in result.items:
            assert item.release_date >= "2023-01-01"

    def test_multi_choices_filter(self, adapter):
        result = adapter.list(
            ProductResource,
            filters={"product_type__in": ["physical", "digital"]},
        )
        for item in result.items:
            assert item.product_type in ("physical", "digital")

    def test_unknown_category_in_seed_data(self, adapter):
        item = adapter.get(ProductResource, "prod-6")
        assert item is not None
        assert item.category_id == "unknown-cat"


class TestExampleFKDisplayFallback:
    def test_known_category_resolves_name(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter

        admin = ExampleProductAdmin()
        config = ProductResource.get_field_config("category_id")
        resolved = admin.resolve_fk_value("category_id", config, "cat-1")
        assert resolved == "Electronics"

    def test_unknown_category_returns_none_with_display_field(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter

        admin = ExampleProductAdmin()
        config = ProductResource.get_field_config("category_id")
        resolved = admin.resolve_fk_value("category_id", config, "unknown-cat")
        assert resolved is None


class TestExampleAdminPermissionHooks:
    def test_category_admin_denies_delete(self):
        class ExampleCategoryAdmin(GrpcResourceAdmin):
            resource_class = CategoryResource
            adapter_class = CatalogGrpcAdapter
            grpc_enable_delete = True

            def has_grpc_delete_permission(self, request, obj=None):
                return False

        admin = ExampleCategoryAdmin()
        request = RequestFactory().get("/")
        assert admin.has_delete_permission(request) is False

    def test_product_admin_hooks(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter
            grpc_enable_create = True
            grpc_enable_update = True
            grpc_enable_delete = True
            grpc_form_fields = ["name"]

            def has_grpc_add_permission(self, request):
                return True

            def has_grpc_change_permission(self, request, obj=None):
                return True

            def has_grpc_delete_permission(self, request, obj=None):
                return False

            def has_grpc_view_permission(self, request, obj=None):
                return True

        admin = ExampleProductAdmin()
        request = RequestFactory().get("/")
        assert admin.has_add_permission(request) is True
        assert admin.has_change_permission(request) is True
        assert admin.has_delete_permission(request) is False
        assert admin.has_view_permission(request) is True


class TestExampleAdminValidationHooks:
    def test_clean_name_strips_whitespace(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter

            def clean_name(self, value):
                return value.strip() if isinstance(value, str) else value

        admin = ExampleProductAdmin()
        assert admin.clean_name("  widget  ") == "widget"

    def test_clean_price_rounds(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter

            def clean_price(self, value):
                return round(value, 2) if value is not None else value

        admin = ExampleProductAdmin()
        assert admin.clean_price(19.999) == 20.0

    def test_clean_grpc_data_applies_hooks(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter

            def clean_name(self, value):
                return value.strip()

            def clean(self, data):
                if data.get("price") is not None and data["price"] <= 0:
                    from django import forms

                    raise forms.ValidationError("Price must be greater than zero.")
                return data

        admin = ExampleProductAdmin()
        cleaned = admin.clean_grpc_data({"name": "  widget  ", "price": 10.0})
        assert cleaned["name"] == "widget"

        with pytest.raises(forms.ValidationError):
            admin.clean_grpc_data({"name": "widget", "price": 0})


class TestExampleFormBuilder:
    def test_form_excludes_controlled_fields(self):
        from django_admin_grpc.forms import FormBuilder

        form_class = FormBuilder.build(ProductResource)
        field_names = list(form_class.base_fields.keys())
        assert "id" not in field_names  # readonly
        assert "sku" not in field_names  # editable=False
        assert "notes" not in field_names  # detail_only
        assert "badge" not in field_names  # list_only
        assert "name" in field_names


class TestExampleFilterConfig:
    def test_advanced_filters_pass_through(self):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter
            grpc_filter_config = {
                "price": {"type": "number_range", "label": "Price"},
                "rating": {"type": "number_range", "label": "Rating"},
                "release_date": {
                    "type": "date_range",
                    "label": "Release Date",
                },
                "product_type": {
                    "type": "multi_choices",
                    "choices": [
                        ("physical", "Physical"),
                        ("digital", "Digital"),
                        ("service", "Service"),
                    ],
                },
            }

        admin = ExampleProductAdmin()
        request = RequestFactory().get(
            "/?price__gte=10&price__lte=100&rating__gte=3"
            "&release_date__gte=2023-01-01&product_type=physical,digital"
        )
        filters = admin.get_grpc_filters(request)
        assert filters["price__gte"] == "10"
        assert filters["price__lte"] == "100"
        assert filters["rating__gte"] == "3"
        assert filters["release_date__gte"] == "2023-01-01"
        assert filters["product_type"] == ["physical", "digital"]


class TestExampleGrpcAction:
    def test_bulk_activate_action(self, adapter):
        class ExampleProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            adapter_class = CatalogGrpcAdapter
            actions = ["bulk_activate"]

            @grpc_action(description="Activate selected products")
            def bulk_activate(self, request, selected_pks):
                return self.apply_grpc_bulk_update(request, selected_pks, {"active": True})

        admin = ExampleProductAdmin(admin_site=AdminSite())
        request = RequestFactory().post("/")
        qs = Mock()
        qs._selected_pks = ["prod-1", "prod-2"]

        action_func = admin.get_actions(request)["bulk_activate"][0]
        updated, errors = action_func(admin, request, qs)
        assert updated == 2
        assert errors == 0

        for pk in ("prod-1", "prod-2"):
            item = adapter.get(ProductResource, pk)
            assert item.active is True
