"""
Catalog resources for the django-admin-grpc example.

Demonstrates how a consumer project defines remote entities using
BaseGrpcResource and field config classes.
"""
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    ChoicesFieldConfig,
    DateFieldConfig,
    FKFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
    TextFieldConfig,
)


def _load_category_choices():
    """Lazy loader for category FK choices (avoids circular import)."""
    from .adapters import CatalogGrpcAdapter

    adapter = CatalogGrpcAdapter()
    return [(c["id"], c["name"]) for c in adapter._categories.values()]


class CategoryResource(BaseGrpcResource):
    """Represents a Product Category from the Catalog microservice."""

    class Meta:
        app_label = "catalog"
        model_name = "category"
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id", label="ID", readonly=True),
        CharFieldConfig(name="name", label="Name", max_length=100),
        TextFieldConfig(name="description", label="Description", required=False),
        BooleanFieldConfig(name="active", label="Active", initial=True),
    ]


class ProductResource(BaseGrpcResource):
    """Represents a Product from the Catalog microservice."""

    class Meta:
        app_label = "catalog"
        model_name = "product"
        verbose_name = "Product"
        verbose_name_plural = "Products"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id", label="ID", readonly=True),
        CharFieldConfig(name="sku", label="SKU", max_length=50, editable=False),
        CharFieldConfig(name="name", label="Name", max_length=200),
        TextFieldConfig(name="description", label="Description", required=False),
        TextFieldConfig(
            name="notes", label="Internal Notes", required=False, detail_only=True
        ),
        CharFieldConfig(
            name="badge", label="Badge", max_length=50, required=False, list_only=True
        ),
        FloatFieldConfig(name="price", label="Price"),
        IntegerFieldConfig(name="rating", label="Rating", required=False),
        DateFieldConfig(name="release_date", label="Release Date", required=False),
        BooleanFieldConfig(name="active", label="Active", initial=True),
        ChoicesFieldConfig(
            name="product_type",
            label="Product Type",
            required=False,
            choices=[
                ("physical", "Physical"),
                ("digital", "Digital"),
                ("service", "Service"),
            ],
        ),
        FKFieldConfig(
            name="category_id",
            label="Category",
            service="catalog_category",
            get_method="get_category",
            display_field="name",
            required=False,
            choices_loader=_load_category_choices,
        ),
    ]
