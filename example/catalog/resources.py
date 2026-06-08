"""
Catalog resources for the django-grpc-admin example.

Demonstrates how a consumer project defines remote entities using
BaseGrpcResource and field config classes.
"""
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FKFieldConfig,
    FloatFieldConfig,
    TextFieldConfig,
)


class CategoryResource(BaseGrpcResource):
    """Represents a Product Category from the Catalog microservice."""

    class Meta:
        app_label = "catalog"
        model_name = "category"
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id", label="ID"),
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
        CharFieldConfig(name="id", label="ID"),
        CharFieldConfig(name="name", label="Name", max_length=200),
        TextFieldConfig(name="description", label="Description", required=False),
        FloatFieldConfig(name="price", label="Price"),
        BooleanFieldConfig(name="active", label="Active", initial=True),
        FKFieldConfig(
            name="category_id",
            label="Category",
            service="catalog_category",
            get_method="get_category",
            display_field="name",
            required=False,
        ),
    ]
