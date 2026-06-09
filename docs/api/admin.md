# API Reference — Admin

## `GrpcResourceAdmin`

Admin class for resources fetched from a gRPC service. Inherits from Django's `ModelAdmin`.

### Class Attributes

#### `resource_class: type`

**Required.** The `BaseGrpcResource` subclass.

```python
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
```

#### `service_name: str`

Service name in the adapter registry. Alternative to `adapter_class`.

```python
class ProductAdmin(GrpcResourceAdmin):
    service_name = "catalog"
```

#### `adapter_class: type | None`

Adapter class or instance. Alternative to `service_name`.

```python
class ProductAdmin(GrpcResourceAdmin):
    adapter_class = CatalogAdapter
```

#### `grpc_filter_config: dict | list`

Filter configuration. See [Filters](../admin-guide/filters.md).

```python
grpc_filter_config = ["active", "status"]
# or
grpc_filter_config = {
    "active": {"type": "boolean"},
    "status": {"type": "choices", "choices": [("a", "A")]},
}
```

#### `grpc_form_fields: list[str]`

Fields to include in add/change forms.

```python
grpc_form_fields = ["name", "price", "active"]
```

#### `grpc_enable_create: bool`

Show "Add" button. Default: `False`.

#### `grpc_enable_update: bool`

Allow editing. Default: `False`.

#### `grpc_enable_delete: bool`

Show delete button. Default: `False`.

#### `grpc_detail_fields: list`

Fields shown in the read-only detail section.

```python
grpc_detail_fields = ["id", "name", "created_at"]
# or with custom labels:
grpc_detail_fields = [("Product ID", "id"), ("Name", "name")]
```

#### `grpc_cursor_pagination: bool`

Use cursor-based pagination. Default: `False`.

### Class Methods

#### `with_base(base_admin_class) -> type`

Return a new admin class that inherits from the given base.

```python
from unfold.admin import ModelAdmin as UnfoldModelAdmin

MyGrpcAdmin = GrpcResourceAdmin.with_base(UnfoldModelAdmin)

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
```

### Methods

#### `get_adapter()`

Return the gRPC adapter. Looks up by `adapter_class` or `service_name`.

#### `get_changelist(request, **kwargs)`

Return `GrpcChangeList`.

#### `get_queryset(request)`

Return a `GrpcFakeQuerySet`.

#### `get_grpc_filters(request) -> dict`

Extract filter parameters from the request.

Override to add custom filters:

```python
def get_grpc_filters(self, request):
    filters = super().get_grpc_filters(request)
    filters["tenant_id"] = request.user.tenant_id
    return filters
```

#### `fetch_list(page=1, page_size=25, filters=None) -> PagedResult | dict`

Call the adapter's `list()` method.

#### `fetch_one(pk: str) -> ModelWrapper | None`

Call the adapter's `get()` method and wrap the result.

#### `get_object(request, object_id, from_field=None) -> ModelWrapper | None`

Retrieve a single object for the change view.

#### `_build_form_class()`

Build the form class for add/change views. Override to customize widgets.

```python
def _build_form_class(self):
    return self.resource_class.build_form_class(widgets={
        "description": forms.Textarea(attrs={"rows": 8}),
    })
```

#### `get_grpc_form_initial(obj) -> dict`

Return initial data for the change form.

```python
def get_grpc_form_initial(self, obj):
    initial = super().get_grpc_form_initial(obj)
    initial["tags"] = ", ".join(obj.tags or [])
    return initial
```

#### `get_grpc_create_data(cleaned_data) -> dict`

Transform data before `adapter.create()`. Override to add computed fields.

```python
def get_grpc_create_data(self, cleaned_data):
    data = dict(cleaned_data)
    data["created_by"] = self.request.user.username
    return data
```

#### `get_grpc_update_data(obj, cleaned_data) -> dict`

Transform data before `adapter.update()`.

```python
def get_grpc_update_data(self, obj, cleaned_data):
    data = dict(cleaned_data)
    data["updated_by"] = self.request.user.username
    return data
```

#### `get_grpc_detail_fields() -> list[tuple[str, str]]`

Return (label, field_name) pairs for the detail section.

#### `get_grpc_detail_rows(obj) -> list[dict]`

Return detail rows with label, value, and type flags.

#### `resolve_fk_value(field_name, config, fk_id) -> str | None`

Resolve a foreign key value to a display string when `FKFieldConfig.display_field` is configured. Supports Django model lookups and gRPC service lookups. If `display_field` is not configured, the raw FK value is returned.

### Permission Methods

#### `has_add_permission(request) -> bool`

`grpc_enable_create` AND `_can_create()`.

#### `has_change_permission(request, obj=None) -> bool`

Delegates to `has_view_permission`.

#### `has_delete_permission(request, obj=None) -> bool`

`_can_delete()`.

#### `has_view_permission(request, obj=None) -> bool`

Always `True` by default.

### Views

#### `changelist_view(request, extra_context=None)`

List view.

#### `add_view(request, form_url="", extra_context=None)`

Add view. Builds form, validates POST, calls `adapter.create()`.

#### `change_view(request, object_id, form_url="", extra_context=None)`

Change view. Fetches object, builds form, validates POST, calls `adapter.update()`.

#### `delete_view(request, object_id, extra_context=None)`

Delete view. Fetches object, confirms POST, calls `adapter.delete()`.

## `grpc_action`

Decorator for gRPC admin actions. Wraps a method so it receives
``selected_pks`` (a list of primary keys) instead of a Django queryset.

```python
from django_admin_grpc.admin import GrpcResourceAdmin, grpc_action
from django.contrib import messages

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

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `description` | `str` | `""` | Label shown in the action dropdown. Defaults to the method name. |
| `permissions` | `list[str]` | `None` | Permission codenames required to use this action. |

### Compatibility

- Standard Django ``@admin.action`` still works alongside ``@grpc_action``.
- ``apply_grpc_bulk_update`` accepts either a queryset or a list of PKs,
  so both decorated and standard actions work seamlessly.

## `GrpcChangeList`

Custom `ChangeList` that populates results by calling the adapter.

### Methods

#### `get_filters(request) -> tuple`

Build filter specs from `grpc_filter_config`.

#### `get_results(request)`

Fetch results from the adapter and populate `result_list`, `result_count`, and `paginator`.
