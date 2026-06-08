# Filters

Filters in django-grpc-admin appear in the sidebar of list views, just like standard Django Admin. They do not touch the database — instead, they pass query-string parameters to the adapter's `list()` method.

## Simple Filter List

The simplest way to enable filters is to set `grpc_filter_config` to a list of field names:

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    list_filter = ["active", "status"]
    grpc_filter_config = ["active", "status"]
```

The admin auto-detects the field type from the resource's field config and renders the appropriate filter widget:

- `boolean` fields → Yes/No/All dropdown
- `choices` fields → Choice dropdown
- All other types → Text input

## Dict-Based Filter Configuration

For more control, use a dict to override the type, label, or choices per field:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_filter = ["active", "status", "name"]
    grpc_filter_config = {
        "active": {"type": "boolean"},
        "status": {
            "type": "choices",
            "choices": [
                ("draft", "Draft"),
                ("live", "Live"),
                ("archived", "Archived"),
            ],
        },
        "name": {"type": "text", "label": "Product Name"},
    }
```

### Dict Options

| Key | Type | Description |
|-----|------|-------------|
| `type` | `str` | Filter type: `boolean`, `choices`, or `text`. |
| `choices` | `list[tuple]` | Required when `type="choices"`. |
| `label` | `str` | Custom label for the filter. |

## Supported Filter Types

### Boolean Filter

Renders a dropdown with "All", "Yes", and "No" options. The selected value is passed to the adapter as `active__exact=1` or `active__exact=0`.

```python
grpc_filter_config = {
    "active": {"type": "boolean"},
}
```

### Choices Filter

Renders a dropdown with the provided choices. The selected value is passed to the adapter as `status__exact=draft`.

```python
grpc_filter_config = {
    "status": {
        "type": "choices",
        "choices": [
            ("draft", "Draft"),
            ("live", "Live"),
            ("archived", "Archived"),
        ],
    },
}
```

### Text Filter

Renders a text input. The entered value is passed to the adapter as `name=widget`.

```python
grpc_filter_config = {
    "name": {"type": "text", "label": "Product Name"},
}
```

## Custom Filters

For complex filtering logic, subclass `GrpcSimpleListFilter` (modelled on Django's `SimpleListFilter`):

```python
from django_grpc_admin.filters import GrpcSimpleListFilter

class PriceRangeFilter(GrpcSimpleListFilter):
    title = "Price Range"
    parameter_name = "price_range"

    def lookups(self, request, model_admin):
        return [
            ("low", "Under $10"),
            ("mid", "$10 – $50"),
            ("high", "Over $50"),
        ]

class ProductAdmin(GrpcResourceAdmin):
    list_filter = ["active", PriceRangeFilter]
```

The filter's `parameter_name` becomes a key in the `filters` dict passed to the adapter.

## How Filters Reach the Adapter

1. User selects a filter value in the sidebar
2. The browser reloads the page with query-string parameters (e.g. `?active__exact=1`)
3. `GrpcResourceAdmin.get_grpc_filters()` extracts filter parameters from `request.GET`
4. The filters dict is passed to `adapter.list(resource_class, filters={"active__exact": "1"})`
5. Your adapter forwards the filters to the gRPC service

### Adapter-Side Filter Handling

```python
def list(self, resource_class, page=1, page_size=25, filters=None):
    filters = filters or {}
    request = ListProductsRequest(
        page=page,
        page_size=page_size,
        active=filters.get("active__exact"),
        status=filters.get("status__exact"),
        name_search=filters.get("name"),
    )
    response = self.stub.ListProducts(request)
    ...
```

!!! tip "Normalize filter keys"
    The admin passes filter keys as they appear in the query string (e.g. `active__exact`). You may want to normalize them in your adapter before sending to gRPC.

    ```python
    def _normalize_filters(self, filters):
        return {k.replace("__exact", ""): v for k, v in filters.items()}
    ```

## Combining Filters and Search

Filters and search work together. When both are active, the adapter receives both in the `filters` dict:

```python
{
    "active__exact": "1",
    "status__exact": "live",
    "search": "widget",
}
```

## Disabling Filters

Set `grpc_filter_config = None` or omit `list_filter` to disable sidebar filters.

## Filter Templates

The built-in filters use Django Admin's default templates. If you use a custom admin theme (e.g. django-unfold), you can subclass the filter classes and set a custom `template`:

```python
from django_grpc_admin.filters import GrpcTextInputFilter

class UnfoldTextFilter(GrpcTextInputFilter):
    template = "unfold/filters/filters_field.html"
```
