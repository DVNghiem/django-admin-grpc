# django-admin-grpc

Django Admin backed by gRPC services — no ORM required.

[![PyPI version](https://badge.fury.io/py/django-admin-grpc.svg)](https://pypi.org/project/django-admin-grpc/)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Django versions](https://img.shields.io/badge/django-5.x%20%7C%206.x-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/DVNghiem/django-admin-grpc/actions/workflows/ci.yml/badge.svg)](https://github.com/DVNghiem/django-admin-grpc/actions/workflows/ci.yml)

---

**django-admin-grpc** lets you expose remote gRPC microservices inside Django Admin with full list, create, update, delete and search support. You define a resource schema, wire a gRPC adapter, and register a single admin class — the package handles forms, pagination, filtering, and error mapping for you.

## Installation

```bash
pip install django-admin-grpc
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
| `fk` | `Select` | Model FKs load options automatically; service/custom FKs use `choices` or `choices_loader`. |
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
  - `display_field` — field to show in detail views; omitted means show the raw FK value.
  - `service` — service name in the adapter registry for gRPC FK resolution.
  - `get_method` — adapter method to call for gRPC FK resolution (default: `get`).
  - `choices` — static `(value, label)` select options for service/custom FK fields.
  - `choices_loader` — callable returning `(value, label)` options for service/custom FK fields.

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
            self._channel = self._create_channel("network-service:50051")
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

`GrpcResourceAdmin` ships with bulk actions out of the box. When the adapter supports delete, a "Delete selected records" action is registered automatically. Opt-in flags expose additional bulk actions for create and update.

**Custom bulk actions with `@grpc_action`:**

```python
from django.contrib import messages
from django_admin_grpc.admin import GrpcResourceAdmin, grpc_action

class ProductAdmin(GrpcResourceAdmin):
    actions = ["activate_selected"]

    @grpc_action(description="Activate selected products")
    def activate_selected(self, request, selected_pks):
        updated, errors = self.apply_grpc_bulk_update(
            request, selected_pks, {"active": True}
        )
        if updated:
            messages.success(request, f"Activated {updated} product(s).")
```

**Single-field bulk action with `@bulk_grpc_action`:**

```python
from django_admin_grpc.admin import bulk_grpc_action

class ProductAdmin(GrpcResourceAdmin):
    actions = ["deactivate_selected"]

    @bulk_grpc_action(description="Deactivate selected", field="active", value=False)
    def deactivate_selected(self, request, selected_pks):
        # Custom side effects allowed; the decorator already applied
        # {active: False} via the adapter's bulk update.
        ...
```

The `@bulk_grpc_action` decorator works with both parenthesised
(`@bulk_grpc_action(...)`) and bare (`@bulk_grpc_action`) invocations.

---

## Batch Operations

The package exposes chunked, partial-failure-aware bulk operations on every adapter. The defaults loop `create()` / `update()` / `delete()` in chunks so you get safe, well-defined behaviour even when the backing service does not offer a true batch endpoint.

| Adapter method | Returns on success | Raises on partial failure |
|----------------|--------------------|---------------------------|
| `adapter.bulk_create(resource_class, items, batch_size=None)` | `list[BaseGrpcResource]` of created items | `GrpcBatchPartialError` with `succeeded` and `failed` |
| `adapter.bulk_update(resource_class, items, batch_size=None)` | `list[BaseGrpcResource]` of updated items | `GrpcBatchPartialError` with the failed PKs |
| `adapter.bulk_delete(resource_class, pks, batch_size=None)` | `{"deleted": int, "failed": []}` | `GrpcBatchPartialError` with the failed PKs |

Every bulk method honours the adapter's `batch_size` attribute (default `100`) and an explicit `batch_size` override. Items that fail are accumulated in the exception's `failed` mapping — keys are the original PK (or input index for `bulk_create`); values are the underlying exception. Per-failure log entries record only the resource name, the PK (or item index), and the exception message — raw input payloads are intentionally not logged because they may contain sensitive fields.

```python
from django_admin_grpc.exceptions import GrpcBatchPartialError

adapter = MyAdapter()
try:
    deleted = adapter.bulk_delete(ProductResource, ["1", "2", "3"])
    print(deleted)
    # {'deleted': 3, 'failed': []}
except GrpcBatchPartialError as exc:
    print(f"{len(exc.succeeded)} OK, {len(exc.failed)} failed")
    for failed_pk, err in exc.failed.items():
        print(f"  pk={failed_pk} → {err}")
```

**Async adapters** (`BaseAsyncGrpcServiceAdapter`) ship the same `bulk_create` / `bulk_update` / `bulk_delete` coroutines with identical signatures.

**Built-in admin actions.** `BulkActionMixin` (mixed into `GrpcResourceAdmin`) registers these automatically:

| Action | Visible when | Behaviour |
|--------|--------------|-----------|
| `bulk_delete_action` | `grpc_enable_delete = True` and the adapter supports delete | Delegates to `apply_grpc_bulk_delete` → adapter's `bulk_delete` |
| `bulk_create_action` | `grpc_bulk_create_enabled = True` and the adapter supports create | Builds one record per selected PK via `build_bulk_create_payload` and calls `adapter.bulk_create` |
| `bulk_update_action` | `grpc_bulk_update_enabled = True` and the adapter supports update | Builds the update payload via `build_bulk_update_payload` and calls `adapter.bulk_update` |

Override `build_bulk_create_payload` / `build_bulk_update_payload` on the admin class to customise the per-row payload. Django's default `delete_selected` is removed.

**Customising the bulk delete result.** The `apply_grpc_bulk_delete` helper posts a Django `messages.success` line on full success, a `messages.error` summary plus per-PK error messages on partial failure, and returns the adapter's `{deleted, failed}` summary so you can layer extra logic on top.

---

## Error Handling

| gRPC Status Code | Mapped Exception | Admin Behavior |
|------------------|------------------|----------------|
| `NOT_FOUND` | `GrpcNotFoundError` | Redirects to "object does not exist" page. |
| `PERMISSION_DENIED` / `UNAUTHENTICATED` | `GrpcPermissionDeniedError` | Shown as red error message; user stays on the page. |
| `INVALID_ARGUMENT` | `GrpcInvalidArgumentError` | Shown as red error message (validation failed). |
| `ALREADY_EXISTS` | `GrpcAlreadyExistsError` | Shown as red error message ("Record already exists"). |
| `FAILED_PRECONDITION` | `GrpcFailedPreconditionError` | Shown as red error message. |
| `RESOURCE_EXHAUSTED` | `GrpcResourceExhaustedError` | Shown as yellow warning ("Service is busy, try again later"). |
| `ABORTED` | `GrpcAbortedError` | Shown as yellow warning ("Request aborted, please retry"). |
| `CANCELLED` | `GrpcCancelledError` | Shown as yellow warning ("Request was cancelled"). |
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

## Channel Pooling

For services called from many admin views, create a shared `GrpcChannelPool` and attach it to the adapter.  The pool keeps channels ready, recycles them, and runs background health checks.

```python
from django_admin_grpc import GrpcChannelPool
from django_admin_grpc.adapters import BaseGrpcServiceAdapter

class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def __init__(self):
        self.grpc_pool = GrpcChannelPool("dns:///catalog-service:50051")

    def list(self, resource_class, page=1, page_size=25, filters=None):
        with self.get_channel() as channel:
            stub = CatalogStub(channel)
            ...
```

`GrpcChannelPool` reads defaults from Django settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `GRPC_ADMIN_POOL_MIN_SIZE` | `2` | Minimum idle channels to keep ready. |
| `GRPC_ADMIN_POOL_MAX_SIZE` | `10` | Maximum channels open at once. |
| `GRPC_ADMIN_POOL_MAX_IDLE_SECONDS` | `300.0` | Evict idle channels after this many seconds. |
| `GRPC_ADMIN_POOL_HEALTH_CHECK_INTERVAL` | `30.0` | Seconds between background health passes. |
| `GRPC_ADMIN_POOL_HEALTH_CHECK_TIMEOUT` | `2.0` | Timeout for `channel_ready()` health probes. |

Call `pool.metrics()` for a snapshot of `pool_size`, `idle`, `in_use`, and `evicted_total`.

## Async Adapters

Use `BaseAsyncGrpcServiceAdapter` and `AsyncAdapterRegistry` with `grpc.aio`:

```python
from django_admin_grpc import BaseAsyncGrpcServiceAdapter, AsyncAdapterRegistry
import grpc.aio

class CatalogAsyncAdapter(BaseAsyncGrpcServiceAdapter):
    service_name = "catalog"
    target = "dns:///catalog-service:50051"

    async def list(self, resource_class, page=1, page_size=25, filters=None):
        channel = await self.channel()
        stub = CatalogStub(channel)
        ...

    async def get(self, resource_class, pk):
        ...

async_registry = AsyncAdapterRegistry()
async_registry.register("catalog", CatalogAsyncAdapter())
```

In the admin, subclass `AsyncGrpcResourceAdmin`.  It detects async adapters and automatically bridges async `list`/`get`/`create`/`update` calls into Django's synchronous request/response cycle.  For ASGI deployments you can route the changelist to `async_changelist_view`.

```python
from django_admin_grpc import AsyncGrpcResourceAdmin

@admin.register(Product.admin_model())
class ProductAdmin(AsyncGrpcResourceAdmin):
    resource_class = Product
    service_name = "catalog"
```

---

## Caching

Read-through caching for `list()` and `get()` is opt-in via the `CachedAdapterMixin`. When caching is enabled, the mixin caches successful list/get results, caches `None` for "not found" lookups, and invalidates the resource namespace on every write (create/update/delete and their `bulk_*` counterparts).

**Enable in `settings.py`:**

```python
GRPC_ADMIN = {
    "CACHE_ENABLED": True,        # default False
    "CACHE_TTL": 60,              # seconds
    "CACHE_PREFIX": "grpc_admin", # key namespace
    "CACHE_BACKEND": "default",   # Django CACHES alias
}
```

**Combine the mixin with your adapter:**

```python
from django_admin_grpc import BaseGrpcServiceAdapter, CachedAdapterMixin
from django_admin_grpc.paginator import PagedResult

# Step 1: implement the gRPC stubs in a plain adapter.  The mixin must NOT be
# combined with this class directly — the concrete ``list``/``get`` below
# would shadow the caching layer the mixin provides.
class BaseCatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        ...
        return PagedResult(items=items, total=total, page=page, page_size=page_size)

    def get(self, resource_class, pk):
        ...

# Step 2: layer the caching mixin on top.  CachedAdapterMixin overrides
# ``list``/``get`` to consult the cache, and inherits the actual gRPC
# implementation from ``BaseCatalogAdapter`` via ``super()``.
class CatalogAdapter(CachedAdapterMixin, BaseCatalogAdapter):
    pass
```

The mixin is fully transparent: if caching is disabled globally, if the mixin is not in the adapter MRO, or if the instance sets `grpc_cache = None`, the adapter falls through to the base implementation unchanged. Cache keys are stable SHA-256 hashes of the sorted JSON-encoded kwargs, namespaced by the resource class and operation name, so two callers passing the same arguments in different order hit the same entry.

**Override per adapter.** Set `grpc_cache = GrpcAdminCache(prefix="custom", ttl=120, enabled=True)` on the instance to use a different prefix, TTL, or backend than the global settings. The constructor of `GrpcAdminCache` never raises; an unknown backend silently disables caching.

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
| `GRPC_ADMIN_CACHE_ENABLED` | `False` | Enable `CachedAdapterMixin` globally. |
| `GRPC_ADMIN_CACHE_TTL` | `60` | Default TTL in seconds. |
| `GRPC_ADMIN_CACHE_PREFIX` | `"grpc_admin"` | Cache-key namespace. |
| `GRPC_ADMIN_CACHE_BACKEND` | `"default"` | Django `CACHES` alias. |
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
