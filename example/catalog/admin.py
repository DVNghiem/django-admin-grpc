"""
Catalog admin registration for the django-admin-grpc example.

Demonstrates how a consumer project wires resources into Django Admin
using GrpcResourceAdmin.
"""
from django import forms
from django.contrib import admin, messages

from django_admin_grpc.admin import GrpcResourceAdmin, grpc_action

from .adapters import CatalogGrpcAdapter, CategoryAdapter
from .resources import CategoryResource, ProductResource


@admin.register(CategoryResource.admin_model())
class CategoryAdmin(GrpcResourceAdmin):
    """Admin for Categories (gRPC-backed, in-memory)."""

    resource_class = CategoryResource
    adapter_class = CategoryAdapter

    list_display = ["id", "name", "active"]
    list_filter = ["active"]
    search_fields = ["name", "description"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "description", "active"]

    def has_grpc_delete_permission(self, request, obj=None):
        """Deny deletion of categories in this example."""
        return False


@admin.register(ProductResource.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    """Admin for Products (gRPC-backed, in-memory)."""

    resource_class = ProductResource
    adapter_class = CatalogGrpcAdapter

    list_display = [
        "id",
        "name",
        "sku",
        "price",
        "rating",
        "active",
        "category_id",
        "badge",
    ]
    search_fields = ["name", "description"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = [
        "name",
        "description",
        "price",
        "active",
        "category_id",
        "rating",
        "release_date",
        "product_type",
    ]

    grpc_filter_config = {
        "active": {"type": "boolean"},
        "category_id": {
            "type": "choices",
            "choices": [
                ("cat-1", "Electronics"),
                ("cat-2", "Books"),
                ("cat-3", "Clothing"),
            ],
        },
        "price": {"type": "number_range", "label": "Price"},
        "rating": {"type": "number_range", "label": "Rating"},
        "release_date": {"type": "date_range", "label": "Release Date"},
        "product_type": {
            "type": "multi_choices",
            "choices": [
                ("physical", "Physical"),
                ("digital", "Digital"),
                ("service", "Service"),
            ],
        },
    }

    actions = ["bulk_activate"]

    # ── Permission hooks ───────────────────────────────────────────────────

    def has_grpc_add_permission(self, request):
        return True

    def has_grpc_change_permission(self, request, obj=None):
        return True

    def has_grpc_delete_permission(self, request, obj=None):
        return True

    def has_grpc_view_permission(self, request, obj=None):
        return True

    # ── Validation hooks ───────────────────────────────────────────────────

    def clean_name(self, value):
        """Strip surrounding whitespace from the product name."""
        return value.strip() if isinstance(value, str) else value

    def clean_price(self, value):
        """Round price to two decimal places."""
        return round(value, 2) if value is not None else value

    def clean(self, data):
        """Cross-field validation."""
        cleaned = dict(data)
        if cleaned.get("price") is not None and cleaned["price"] <= 0:
            raise forms.ValidationError("Price must be greater than zero.")
        return cleaned

    # ── Custom gRPC action ─────────────────────────────────────────────────

    @grpc_action(description="Activate selected products")
    def bulk_activate(self, request, selected_pks):
        updated, errors = self.apply_grpc_bulk_update(
            request, selected_pks, {"active": True}
        )
        if updated:
            messages.success(request, f"Activated {updated} product(s).")
        if errors:
            messages.error(request, f"Failed to activate {errors} product(s).")

    def _build_form_class(self):
        # Example: override widgets for specific fields
        return self.resource_class.build_form_class(
            widgets={
                "description": forms.Textarea(attrs={"rows": 6}),
                "price": forms.NumberInput(attrs={"step": "0.01"}),
            }
        )
