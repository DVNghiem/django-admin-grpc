# Quick Start

This tutorial walks you through creating a complete gRPC-backed admin for a `Product` catalog. By the end, you will have a working Django Admin interface that fetches and edits data from a remote service.

## What You Will Build

A Product admin with:

- List view showing ID, name, price, and status
- Sidebar filters for active/inactive products
- Text search by name and description
- Add, edit, and delete forms
- Pagination

## Step 1: Create a Django app

If you do not have a Django project yet, create one:

```bash
django-admin startproject myproject
cd myproject
python manage.py startapp catalog
```

Add `catalog` and `django_admin_grpc` to `INSTALLED_APPS`.

## Step 2: Define the resource

Create `catalog/resources.py`:

```python
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FloatFieldConfig,
    TextFieldConfig,
)

class Product(BaseGrpcResource):
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
    ]
```

The `BaseGrpcResource` subclass declares what fields exist, their types, and which field is the primary key. This is the schema that drives forms, list columns, and filters.

!!! info "Field config reference"
    See [Resources](../core-concepts/resources.md) for the full list of field types and options.

## Step 3: Write the adapter

Create `catalog/adapters.py`:

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult

class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        # Replace with your actual gRPC call
        items = [
            resource_class(id="1", name="Widget", price=9.99, active=True),
            resource_class(id="2", name="Gadget", price=19.99, active=False),
        ]
        return PagedResult(items=items, total=2)

    def get(self, resource_class, pk):
        # Replace with your actual gRPC call
        return resource_class(id=pk, name="Widget", price=9.99, active=True)

    def create(self, resource_class, data):
        # Replace with your actual gRPC call
        return resource_class(**data)

    def update(self, resource_class, pk, data):
        # Replace with your actual gRPC call
        return resource_class(pk=pk, **data)

    def delete(self, resource_class, pk):
        # Replace with your actual gRPC call
        return True
```

The adapter is the transport layer. It bridges Django Admin and your gRPC service by implementing `list`, `get`, and optionally `create`, `update`, and `delete`.

!!! tip "Use the example project"
    The `example/` directory in this repository contains a complete in-memory adapter that simulates a gRPC service. You can run it without any external server.

## Step 4: Register the admin class

Create `catalog/admin.py`:

```python
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin

from .resources import Product
from .adapters import CatalogAdapter

@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    list_display = ["id", "name", "price", "active"]
    list_filter = ["active"]
    search_fields = ["name", "description"]
    list_per_page = 25

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "description", "price", "active"]
```

`Product.admin_model()` creates a lightweight fake model class that is compatible with Django's `ModelAdmin` machinery. The `@admin.register()` decorator registers it exactly like a real Django model.

## Step 5: Run the server

```bash
python manage.py migrate
python manage.py runserver
```

Navigate to `/admin/catalog/product/` and you will see the Product list powered by your adapter.

## Try It Out

1. Click **Add Product** and fill in the form
2. Return to the list and use the **Active** filter on the right
3. Type "widget" in the search box
4. Click a product name to edit it
5. Use the checkbox column and the action dropdown to delete items

## Next Steps

- Learn how the pieces fit together in [Architecture](../core-concepts/architecture.md)
- Explore all [resource field types](../core-concepts/resources.md)
- Add [filters and search](../admin-guide/filters.md) to your list views
- Customize [forms and widgets](../admin-guide/forms.md)
