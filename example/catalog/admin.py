"""
Catalog admin registration for the django-grpc-admin example.

Demonstrates how a consumer project wires resources into Django Admin
using GrpcResourceAdmin.
"""
from django import forms
from django.contrib import admin

from django_grpc_admin.admin import GrpcResourceAdmin

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


@admin.register(ProductResource.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    """Admin for Products (gRPC-backed, in-memory)."""

    resource_class = ProductResource
    adapter_class = CatalogGrpcAdapter

    list_display = ["id", "name", "price", "active", "category_id"]
    list_filter = ["active", "category_id"]
    search_fields = ["name", "description"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "description", "price", "active", "category_id"]

    def _build_form_class(self):
        # Example: override widgets for specific fields
        return self.resource_class.build_form_class(
            widgets={
                "description": forms.Textarea(attrs={"rows": 6}),
                "price": forms.NumberInput(attrs={"step": "0.01"}),
            }
        )
