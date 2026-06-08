# django-grpc-admin

Django Admin backed by gRPC services — no ORM required.

[![PyPI version](https://badge.fury.io/py/django-grpc-admin.svg)](https://pypi.org/project/django-grpc-admin/)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Django versions](https://img.shields.io/badge/django-5.x%20%7C%206.x-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/DVNghiem/django-admin-grpc/actions/workflows/ci.yml/badge.svg)](https://github.com/DVNghiem/django-admin-grpc/actions/workflows/ci.yml)

---

**django-grpc-admin** lets you expose remote gRPC microservices inside Django Admin with full list, create, update, delete and search support. You define a resource schema, wire a gRPC adapter, and register a single admin class — the package handles forms, pagination, filtering, and error mapping for you.

## Installation

```bash
pip install django-grpc-admin
```

Add the app to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "django_admin_grpc",
]
```

## Quick Start

```python
# resources.py
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FloatFieldConfig,
)

class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        model_name = "product"
        verbose_name = "Product"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id"),
        CharFieldConfig(name="name", max_length=200),
        FloatFieldConfig(name="price"),
        BooleanFieldConfig(name="active", initial=True),
    ]
```

That is all. Django Admin now shows list, add, change, and delete screens powered by your gRPC service.

---

## Package Architecture

| Component | Purpose |
|-----------|---------|
| `BaseGrpcResource` | Declarative schema for a remote entity. Defines fields, primary key, and metadata. |
| `BaseFieldConfig` | Base class for field metadata. Use concrete subclasses like `CharFieldConfig`, `IntegerFieldConfig`, etc. |
| `BaseGrpcServiceAdapter` | Abstract transport layer. Implement `list`, `get`, and optionally `create`, `update`, `delete`. |
| `GrpcResourceAdmin` | `ModelAdmin` subclass that renders lists and forms using the adapter instead of the ORM. |
| `BaseGrpcMapper` | Optional request/response mapper between Django forms and protobuf messages. |
| `PagedResult` | Dataclass returned by `adapter.list()` carrying items, total count, and optional cursor. |
| `AdapterRegistry` | Central registry mapping service names to adapter instances. |

---

## How to Define a New Resource

A resource is a Python class that tells Django Admin what columns exist, what types they are, and which one is the primary key.

```python
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FKFieldConfig,
    IntegerFieldConfig,
)

class NetworkRule(BaseGrpcResource):
    class Meta:
        app_label = "network"
        model_name = "networkrule"
        verbose_name = "Network Rule"
        verbose_name_plural = "Network Rules"
        pk_field = "rule_id"

    fields = [
        CharFieldConfig(name="rule_id", label="Rule ID"),
        CharFieldConfig(name="name", max_length=120),
        IntegerFieldConfig(name="priority"),
        BooleanFieldConfig(name="active", initial=True),
        FKFieldConfig(
            name="partner_id",
            label="Partner",
            model="contacts.Contact",      # resolves via Django ORM
            display_field="name",
            required=False,
        ),
    ]
```

**Supported field types:**

| Type | Form widget | Notes |
|------|-------------|-------|
| `char` | `TextInput` | Use `max_length` to limit input. |
| `text` | `Textarea` | Multi-line text. |
| `integer` | `NumberInput` | Whole numbers. |
| `float` | `NumberInput` | Decimal numbers. |
| `boolean` | `CheckboxInput` | Defaults to `False` unless `initial=True`. |
| `choices` | `Select` | Provide `choices=[("a", "A"), ...]`. |
| `fk` | `Select` | Use `model="app.Model"` for Django lookups or `service="..."` for gRPC lookups. |
| `date` / `datetime` | `DateInput` / `DateTimeInput` | Stored as string; validate in the adapter. |

**Common field options (all subclasses):**

- `name` — field identifier (required).
- `label` — human label (default: auto-title-cased `name`).
- `required` — whether the form field is required (default: `True`).
- `help_text` — shown below the form field.
- `initial` — default value.
- `source` — name of the attribute in the gRPC response if it differs from `name`.

**Type-specific options:**

- `CharFieldConfig`: `max_length` — max characters allowed.
- `ChoicesFieldConfig`: `choices` — list of `(value, label)` tuples.
- `FKFieldConfig`:
  - `model` — `"app_label.ModelName"` for Django FK resolution.
  - `to_field` — model field to use as the FK value.
  - `display_field` — field to show when resolving FK labels.
  - `service` — service name in the adapter registry for gRPC FK resolution.
  - `get_method` — adapter method to call for gRPC FK resolution (default: `get`).

---

## How to Wire gRPC Stubs

An adapter bridges Django Admin and your gRPC service. Subclass `BaseGrpcServiceAdapter` and implement at least `list` and `get`. Implement `create`, `update`, and `delete` only if you need write access.

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult
import grpc

class NetworkRulesAdapter(BaseGrpcServiceAdapter):
    service_name = "network_rules"

    def __init__(self):
        self._channel = None

    @property
    def channel(self):
        if self._channel is None:
            raw = grpc.insecure_channel("network-service:50051")
            self._channel = self._wrap_channel(raw)
        return self._channel

    def list(self, resource_class, page=1, page_size=25, filters=None):
        stub = NetworkRulesStub(self.channel)
        request = ListRulesRequest(page=page, page_size=page_size)
        response = stub.ListRules(request)
        items = [resource_class.from_response(r) for r in response.rules]
        return PagedResult(items=items, total=response.total)

    def get(self, resource_class, pk):
        stub = NetworkRulesStub(self.channel)
        response = stub.GetRule(GetRuleRequest(rule_id=pk))
        return resource_class.from_response(response)

    def create(self, resource_class, data):
        stub = NetworkRulesStub(self.channel)
        request = CreateRuleRequest(**data)
        response = stub.CreateRule(request)
        return resource_class.from_response(response)

    def update(self, resource_class, pk, data):
        stub = NetworkRulesStub(self.channel)
        request = UpdateRuleRequest(rule_id=pk, **data)
        response = stub.UpdateRule(request)
        return resource_class.from_response(response)

    def delete(self, resource_class, pk):
        stub = NetworkRulesStub(self.channel)
        stub.DeleteRule(DeleteRuleRequest(rule_id=pk))
        return True
```

**Registering via the adapter registry (optional):**

```python
from django_admin_grpc.registry import adapter_registry

adapter = NetworkRulesAdapter()
adapter_registry.register("network_rules", adapter)
```

When registered by name, the admin class can reference it with `service_name = "network_rules"` instead of `adapter_class`.

---

## How to Register in Django Admin

Register the resource's fake model with a `GrpcResourceAdmin` subclass:

```python
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin

from .resources import NetworkRule
from .adapters import NetworkRulesAdapter

@admin.register(NetworkRule.admin_model())
class NetworkRuleAdmin(GrpcResourceAdmin):
    resource_class = NetworkRule
    adapter_class = NetworkRulesAdapter   # or service_name = "network_rules"

    list_display = ["rule_id", "name", "active"]
    list_filter = ["active"]
    search_fields = ["name"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "priority", "active", "partner_id"]
```

`Resource.admin_model()` builds a lightweight compatible class with `_meta`, `objects`, `DoesNotExist`, and `MultipleObjectsReturned` so that Django's `ModelAdmin` machinery works without a real ORM model.

---

## How to Customize Forms

By default, forms are built automatically from `grpc_form_fields` and the resource's field config list. You can override widgets or build the form class yourself.

**Custom widgets per field:**

```python
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
    grpc_form_fields = ["name", "description", "price"]

    def _build_form_class(self):
        return self.resource_class.build_form_class(widgets={
            "description": forms.Textarea(attrs={"rows": 8}),
            "price": forms.NumberInput(attrs={"step": "0.01"}),
        })
```

**Using `build_form_class()` on the resource:**

```python
from django import forms

form_class = Product.build_form_class(widgets={
    "name": forms.TextInput(attrs={"class": "vTextField"}),
})
```

**Filtering which fields appear:**

Set `grpc_form_fields` to a subset of the resource's fields. Only those fields will be rendered in add/change views.

**Customizing create/update payloads:**

Override `get_grpc_create_data` and `get_grpc_update_data` on the admin class to transform `cleaned_data` before it reaches the adapter:

```python
class ProductAdmin(GrpcResourceAdmin):
    def get_grpc_create_data(self, cleaned_data):
        data = dict(cleaned_data)
        data["created_by"] = self.request.user.username
        return data
```

---

## How to Customize Permissions

Permissions are controlled by three flags on the admin class:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_enable_create = True   # show "Add" button
    grpc_enable_update = True   # allow editing in change view
    grpc_enable_delete = True   # show delete button and bulk delete action
```

These flags are **ANDed** with adapter capability: if the adapter does not implement `create()`, the add view is disabled automatically even when `grpc_enable_create = True`.

**Hook methods for dynamic permission checks:**

```python
class ProductAdmin(GrpcResourceAdmin):
    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return request.user.groups.filter(name="Admins").exists()
```

---

## How to Customize List Pages

`GrpcResourceAdmin` supports the standard `ModelAdmin` list options:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_display = ["id", "name", "price", "active"]
    list_filter = ["active", "category_id"]
    search_fields = ["name", "description"]
    list_per_page = 25
```

**Filter configuration:**

For list filters to work, declare `grpc_filter_config` as a list or dict:

```python
class ProductAdmin(GrpcResourceAdmin):
    # Simple list — fields are auto-detected by type
    grpc_filter_config = ["active", "category_id"]

    # Dict form — override type or choices per field
    grpc_filter_config = {
        "active": {"type": "boolean"},
        "status": {"type": "choices", "choices": [("draft", "Draft"), ("live", "Live")]},
        "name": {"type": "text", "label": "Product Name"},
    }
```

Supported filter types: `boolean`, `choices`, `text`. The admin renders a sidebar filter panel just like standard Django Admin.

**Pagination:**

By default the adapter receives `page` (1-indexed) and `page_size`. Return a `PagedResult` from `adapter.list()`:

```python
PagedResult(items=instances, total=total_count, page=page, page_size=page_size)
```

For cursor-based pagination, set `grpc_cursor_pagination = True` on the admin. The adapter will receive `page_size` and `filters["cursor"]`. Return the next cursor in `PagedResult.next_cursor`.

---

## How to Customize Actions

Bulk delete is built in. When `grpc_enable_delete = True` and the adapter supports delete, a "Delete selected records" action appears in the dropdown.

**Adding custom actions:**

```python
from django.contrib import messages

class ProductAdmin(GrpcResourceAdmin):
    actions = ["activate_selected"]

    @admin.action(description="Activate selected products")
    def activate_selected(self, request, queryset):
        adapter = self.get_adapter()
        for obj in queryset:
            adapter.update(self.resource_class, obj.pk, {"active": True})
        messages.success(request, "Selected products activated.")
```

Because `queryset` is a `GrpcFakeQuerySet`, iterate over it to access the wrapped resource instances.

---

## Error Handling

gRPC errors are caught at the adapter boundary and mapped to typed exceptions. The admin displays them as Django messages.

| gRPC Status Code | Mapped Exception | Admin Behavior |
|------------------|------------------|----------------|
| `NOT_FOUND` | `GrpcNotFoundError` | Redirects to "object does not exist" page. |
| `PERMISSION_DENIED` / `UNAUTHENTICATED` | `GrpcPermissionDeniedError` | Shown as red error message; user stays on the page. |
| `INVALID_ARGUMENT` | `GrpcInvalidArgumentError` | Shown as red error message (validation failed). |
| `UNAVAILABLE` | `GrpcUnavailableError` | Shown as red error message (service down). |
| `DEADLINE_EXCEEDED` | `GrpcDeadlineExceededError` | Shown as red error message (timeout). |
| Other | `GrpcAdminError` | Shown as generic error message. |

**Mapping errors in your adapter:**

```python
from django_admin_grpc.exceptions import map_grpc_error

class MyAdapter(BaseGrpcServiceAdapter):
    def get(self, resource_class, pk):
        try:
            return self.stub.Get(...)
        except grpc.RpcError as exc:
            raise self._map_rpc_error(exc)
```

You can also catch the typed exceptions in custom admin methods if you need special handling.

---

## Customizing Appearance

### Custom Widgets

You can override widgets per field when building the form class:

```python
from django import forms
from django_admin_grpc.admin import GrpcResourceAdmin

class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
    grpc_form_fields = ["name", "description", "price", "active"]

    def _build_form_class(self):
        return self.resource_class.build_form_class(
            widgets={
                "description": forms.Textarea(attrs={"rows": 8}),
                "price": forms.NumberInput(attrs={"step": "0.01"}),
            }
        )
```

Or set defaults globally in `settings.py`:

```python
GRPC_ADMIN = {
    "DEFAULT_WIDGETS": {
        "char": forms.TextInput,
        "text": forms.Textarea,
        "boolean": forms.CheckboxInput,
    },
}
```

### Custom Admin Base Class

`GrpcResourceAdmin` inherits from Django's `ModelAdmin`. If you use a custom admin theme (e.g. [django-unfold](https://github.com/unfoldadmin/django-unfold), [django-jazzmin](https://github.com/farridav/django-jazzmin), etc.), subclass with the theme's `ModelAdmin` **after** `GrpcResourceAdmin`:

```python
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin

class MyGrpcAdmin(GrpcResourceAdmin, UnfoldModelAdmin):
    pass

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
```

Alternatively, use the factory helper:

```python
MyGrpcAdmin = GrpcResourceAdmin.with_base(UnfoldModelAdmin)
```

### Custom Templates

You can override templates per-resource via the resource `Meta` class:

```python
class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        change_form_template = "myapp/product_change_form.html"
        delete_confirm_template = "myapp/product_delete_confirm.html"
```

Or globally via `settings.py`:

```python
GRPC_ADMIN = {
    "DEFAULT_CHANGE_FORM_TEMPLATE": "myapp/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "myapp/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "myapp/cursor_pagination.html",
}
```

---

## Configuration

Set these in your Django `settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `GRPC_ADMIN_TRACE_CONTEXT_PROVIDER` | `None` | Callable or dotted path that returns a dict of trace headers injected into every gRPC call. |
| `GRPC_ADMIN_DEFAULT_PAGE_SIZE` | `25` | Default items per page for list views. |
| `GRPC_ADMIN_MAX_PAGE_SIZE` | `100` | Maximum items per page. |
| `GRPC_ADMIN_CURSOR_PAGINATION` | `False` | Enable cursor-based pagination globally. |
| `GRPC_ADMIN_LOG_LEVEL` | `"INFO"` | Log level for the package logger. |
| `DEFAULT_WIDGETS` | `None` | Dict mapping field type to widget class or dotted path. |
| `DEFAULT_ADMIN_CLASS` | `django.contrib.admin.ModelAdmin` | Dotted path to the base `ModelAdmin` subclass. |
| `DEFAULT_CHANGE_FORM_TEMPLATE` | `django_admin_grpc/change_form.html` | Template for add/change views. |
| `DEFAULT_DELETE_CONFIRM_TEMPLATE` | `django_admin_grpc/delete_confirm.html` | Template for delete confirmation. |
| `DEFAULT_CURSOR_PAGINATION_TEMPLATE` | `django_admin_grpc/cursor_pagination.html` | Template for cursor pagination controls. |

---

## Example Project

An example Django project is included in the `example/` directory. It demonstrates a catalog microservice with in-memory adapters so you can run the admin locally without a real gRPC server.

```bash
cd example
python manage.py migrate
python manage.py runserver
```

Browse to `/admin/` to see Products and Categories backed by gRPC-style adapters.
---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-change`.
3. Install dev dependencies: `pip install -e '.[dev]'`.
4. Run tests: `pytest`.
5. Open a pull request.

Please include tests for new functionality and keep line coverage at 80% or higher.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
