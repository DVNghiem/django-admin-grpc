"""AI Agent Guide for django-admin-grpc.

This module contains a comprehensive markdown guide that helps AI agents
understand and use the library without external documentation.

Usage:
    import django_admin_grpc
    print(django_admin_grpc.GUIDE)
"""

GUIDE: str = """
# django-admin-grpc — AI Agent Guide

## What is this library?

django-admin-grpc is a Django package that lets you expose remote gRPC microservices
inside Django Admin with full CRUD support (list, create, update, delete, search).
You define a resource schema, wire a gRPC adapter, and register a single admin class.
The package handles forms, pagination, filtering, and error mapping automatically.

No ORM required. No database tables. Works with any gRPC service.

## Installation

```bash
pip install django-admin-grpc
```

Add to `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    # ...
    "django_admin_grpc",
]
```

## Quick Start (3 steps)

### Step 1: Define a Resource

A resource describes the shape of your remote entity:

```python
from django_admin_grpc.resources import BaseGrpcResource, CharFieldConfig, IntegerFieldConfig, BooleanFieldConfig

class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        model_name = "product"
        verbose_name = "Product"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id"),
        CharFieldConfig(name="name", max_length=200),
        IntegerFieldConfig(name="price"),
        BooleanFieldConfig(name="active", initial=True),
    ]
```

### Step 2: Create an Adapter

An adapter bridges Django Admin and your gRPC service:

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult
import grpc

class ProductAdapter(BaseGrpcServiceAdapter):
    service_name = "products"

    def __init__(self):
        self._channel = None

    @property
    def channel(self):
        if self._channel is None:
            raw = grpc.insecure_channel("product-service:50051")
            self._channel = self._wrap_channel(raw)
        return self._channel

    def list(self, resource_class, page=1, page_size=25, filters=None):
        stub = ProductStub(self.channel)
        request = ListProductsRequest(page=page, page_size=page_size)
        response = stub.ListProducts(request)
        items = [resource_class.from_response(r) for r in response.products]
        return PagedResult(items=items, total=response.total)

    def get(self, resource_class, pk):
        stub = ProductStub(self.channel)
        response = stub.GetProduct(GetProductRequest(product_id=pk))
        return resource_class.from_response(response)

    def create(self, resource_class, data):
        stub = ProductStub(self.channel)
        request = CreateProductRequest(**data)
        response = stub.CreateProduct(request)
        return resource_class.from_response(response)

    def update(self, resource_class, pk, data):
        stub = ProductStub(self.channel)
        request = UpdateProductRequest(product_id=pk, **data)
        response = stub.UpdateProduct(request)
        return resource_class.from_response(response)

    def delete(self, resource_class, pk):
        stub = ProductStub(self.channel)
        stub.DeleteProduct(DeleteProductRequest(product_id=pk))
        return True
```

### Step 3: Register in Django Admin

```python
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin
from .resources import Product
from .adapters import ProductAdapter

@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = ProductAdapter

    list_display = ["id", "name", "price", "active"]
    list_filter = ["active"]
    search_fields = ["name"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "price", "active"]
```

## Core Concepts

### Resources (`BaseGrpcResource`)

Resources declare the shape of remote entities. Key attributes:
- `Meta.app_label` — used for URL reversing and app grouping
- `Meta.model_name` — lowercase identifier
- `Meta.verbose_name` / `verbose_name_plural` — display names
- `Meta.pk_field` — primary key field name (default: "id")
- `fields` — list of `BaseFieldConfig` subclasses

Methods:
- `get_field_configs()` — list all field configs
- `get_field_config(name)` — get config for specific field
- `from_response(response)` — create instance from gRPC response
- `admin_model()` — returns a fake Django model compatible with ModelAdmin

### Field Config Types

| Config Class | Type | Options |
|-------------|------|---------|
| `CharFieldConfig` | char | `max_length` |
| `TextFieldConfig` | text | — |
| `IntegerFieldConfig` | integer | — |
| `FloatFieldConfig` | float | — |
| `BooleanFieldConfig` | boolean | `initial` |
| `ChoicesFieldConfig` | choices | `choices=[(value, label), ...]` |
| `DateTimeFieldConfig` | datetime | — |
| `DateFieldConfig` | date | — |
| `FKFieldConfig` | fk | `model`, `to_field`, `display_field`, `service`, `get_method`, `choices`, `choices_loader` |

All field configs support: `name`, `label`, `required`, `help_text`, `initial`, `source`

### Adapters (`BaseGrpcServiceAdapter`)

Abstract base class. Implement at minimum:
- `list(resource_class, page, page_size, filters)` → `PagedResult`
- `get(resource_class, pk)` → resource instance or None

Optionally implement:
- `create(resource_class, data)` → resource instance
- `update(resource_class, pk, data)` → resource instance
- `delete(resource_class, pk)` → bool

Properties:
- `supports_create` / `supports_update` / `supports_delete` — auto-detected

Helpers:
- `_wrap_channel(channel)` — wraps gRPC channel with trace interceptor
- `_map_rpc_error(exc)` — maps gRPC errors to typed exceptions

### Admin (`GrpcResourceAdmin`)

Subclass of Django's `ModelAdmin`. Key attributes:
- `resource_class` — required, your `BaseGrpcResource` subclass
- `adapter_class` or `service_name` — required, how to reach the service
- `grpc_filter_config` — dict or list of filterable fields
- `grpc_form_fields` — fields shown in add/change forms
- `grpc_enable_create` / `grpc_enable_update` / `grpc_enable_delete` — feature flags
- `grpc_cursor_pagination` — use cursor-based pagination
- `grpc_detail_fields` — fields shown in read-only detail view

Methods you can override:
- `get_grpc_create_data(cleaned_data)` — transform data before create
- `get_grpc_update_data(obj, cleaned_data)` — transform data before update
- `get_grpc_form_initial(obj)` — provide initial form values
- `get_grpc_detail_fields()` — customize detail view fields
- `resolve_fk_value(field_name, config, fk_id)` — customize FK resolution

### Paginator (`PagedResult`)

Return from `adapter.list()`:
```python
PagedResult(
    items=[...],           # list of resource instances
    total=100,             # total count for pagination
    page=1,                # current page
    page_size=25,          # items per page
    next_cursor="abc",     # for cursor pagination (optional)
)
```

### Registry (`AdapterRegistry`)

Register adapters by name for reuse:
```python
from django_admin_grpc.registry import adapter_registry
from .adapters import ProductAdapter

adapter_registry.register("products", ProductAdapter())
```

Then in admin:
```python
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    service_name = "products"  # instead of adapter_class
```

## Error Handling

gRPC errors are mapped to typed exceptions:

| gRPC Status | Exception | Behavior |
|------------|-----------|----------|
| NOT_FOUND | `GrpcNotFoundError` | Redirects to "not found" page |
| PERMISSION_DENIED | `GrpcPermissionDeniedError` | Shows red error message |
| INVALID_ARGUMENT | `GrpcInvalidArgumentError` | Shows validation error |
| UNAVAILABLE | `GrpcUnavailableError` | Shows service down message |
| DEADLINE_EXCEEDED | `GrpcDeadlineExceededError` | Shows timeout message |
| Other | `GrpcAdminError` | Generic error message |

In adapters, catch and map errors:
```python
from django_admin_grpc.exceptions import map_grpc_error

def get(self, resource_class, pk):
    try:
        return self.stub.Get(...)
    except grpc.RpcError as exc:
        raise self._map_rpc_error(exc)
```

## Configuration

Settings in `settings.py`:

```python
GRPC_ADMIN = {
    "TRACE_CONTEXT_PROVIDER": None,           # callable returning trace headers dict
    "DEFAULT_PAGE_SIZE": 25,
    "MAX_PAGE_SIZE": 100,
    "CURSOR_PAGINATION": False,
    "LOG_LEVEL": "INFO",
    "DEFAULT_WIDGETS": None,                  # dict mapping field type to widget class
    "DEFAULT_ADMIN_CLASS": "django.contrib.admin.ModelAdmin",
    "DEFAULT_CHANGE_FORM_TEMPLATE": "django_admin_grpc/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "django_admin_grpc/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "django_admin_grpc/cursor_pagination.html",
}
```

## Customizing Appearance

### Custom Admin Base Class

If using django-unfold or another theme:
```python
from django_admin_grpc.admin import GrpcResourceAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin

class MyGrpcAdmin(GrpcResourceAdmin.with_base(UnfoldModelAdmin)):
    pass

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
    adapter_class = ProductAdapter
```

### Custom Templates

Per-resource in Meta:
```python
class Product(BaseGrpcResource):
    class Meta:
        change_form_template = "myapp/product_change_form.html"
```

Or globally in settings (see Configuration section).

## Common Patterns

### Filter Configuration

```python
class ProductAdmin(GrpcResourceAdmin):
    # Simple list — auto-detects field types
    grpc_filter_config = ["active", "category_id"]

    # Dict form — override per field
    grpc_filter_config = {
        "active": {"type": "boolean"},
        "status": {"type": "choices", "choices": [("draft", "Draft"), ("live", "Live")]},
        "name": {"type": "text", "label": "Product Name"},
    }
```

### Custom Widgets

```python
class ProductAdmin(GrpcResourceAdmin):
    def _build_form_class(self):
        return self.resource_class.build_form_class(widgets={
            "description": forms.Textarea(attrs={"rows": 8}),
        })
```

### Foreign Key Resolution

```python
# Django ORM lookup
FKFieldConfig(name="category_id", model="catalog.Category", display_field="name")

# gRPC service lookup with user-defined select options
def load_partners():
    # User-defined logic: call another service, cache results, etc.
    return [("1", "Acme"), ("2", "Globex")]

FKFieldConfig(
    name="partner_id",
    service="partners",
    display_field="company_name",
    choices_loader=load_partners,
)
```

FK fields always render as selects in create/update forms. Model-backed FKs load
options automatically from the Django database. Service/custom FKs should provide
`choices` or `choices_loader`; otherwise the select contains only the empty option.
In detail views, `display_field` controls related-object display. If it is omitted,
the raw FK value is shown.

### Bulk Actions

```python
from django.contrib import messages

class ProductAdmin(GrpcResourceAdmin):
    actions = ["activate_selected"]

    @admin.action(description="Activate selected")
    def activate_selected(self, request, queryset):
        adapter = self.get_adapter()
        for obj in queryset:
            adapter.update(self.resource_class, obj.pk, {"active": True})
        messages.success(request, "Activated selected products.")
```

## Testing

Install dev dependencies:
```bash
pip install -e ".[dev]"
```

Run tests:
```bash
pytest
```

## Key Files

- `src/django_admin_grpc/resources.py` — Resource and field config definitions
- `src/django_admin_grpc/adapters.py` — Base adapter interface
- `src/django_admin_grpc/admin.py` — GrpcResourceAdmin and GrpcChangeList
- `src/django_admin_grpc/filters.py` — gRPC-compatible list filters
- `src/django_admin_grpc/forms.py` — Form builder for resources
- `src/django_admin_grpc/models.py` — Fake model infrastructure
- `src/django_admin_grpc/exceptions.py` — Exception hierarchy
- `src/django_admin_grpc/registry.py` — Adapter registry
"""
