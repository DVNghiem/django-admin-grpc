# List Views

List views in django-grpc-admin work like standard Django Admin list views. You configure `list_display`, `list_filter`, `search_fields`, and pagination exactly as you would for an ORM-backed model.

## list_display

Controls which columns appear in the list view.

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    list_display = ["id", "name", "price", "active"]
```

Each value in `list_display` must match a field name on the resource. The admin calls `getattr(obj, field_name)` to retrieve each cell value.

!!! tip "Custom display methods"
    You can also use callable methods on the admin class, just like standard `ModelAdmin`:

    ```python
    class ProductAdmin(GrpcResourceAdmin):
        list_display = ["id", "name", "formatted_price"]

        @admin.display(description="Price")
        def formatted_price(self, obj):
            return f"${obj.price:.2f}"
    ```

## list_filter

Controls which filters appear in the sidebar. Each value must match a field name on the resource.

```python
class ProductAdmin(GrpcResourceAdmin):
    list_filter = ["active", "category_id"]
```

For filters to work, you must also configure `grpc_filter_config`:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_filter_config = ["active", "category_id"]
```

See [Filters](filters.md) for the full filter configuration guide.

## search_fields

Enables the search box at the top of the list. The search query is passed to the adapter's `list()` method under the `filters["search"]` key.

```python
class ProductAdmin(GrpcResourceAdmin):
    search_fields = ["name", "description"]
```

!!! note "Search is adapter-side"
    The admin passes the search term to the adapter; it does not perform the search itself. Your adapter must forward the search term to the gRPC service.

    ```python
    def list(self, resource_class, page=1, page_size=25, filters=None):
        filters = filters or {}
        search = filters.get("search", "")
        request = ListProductsRequest(page=page, page_size=page_size, search=search)
        ...
    ```

## Pagination

### Offset Pagination (Default)

By default, the adapter receives `page` (1-indexed) and `page_size`. Return a `PagedResult` from `adapter.list()`:

```python
PagedResult(
    items=instances,
    total=total_count,
    page=page,
    page_size=page_size,
)
```

Control the page size with `list_per_page`:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_per_page = 50
```

### Cursor Pagination

For large datasets where offset pagination is inefficient, enable cursor-based pagination:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_cursor_pagination = True
```

When cursor pagination is enabled:

- The adapter receives `page_size` and `filters["cursor"]` instead of `page`
- Return the next cursor in `PagedResult.next_cursor`
- The admin renders a "Next" button instead of numbered page links

```python
def list(self, resource_class, page=1, page_size=25, filters=None):
    filters = filters or {}
    cursor = filters.get("cursor")
    request = ListProductsRequest(page_size=page_size, cursor=cursor or "")
    response = self.stub.ListProducts(request)
    items = [resource_class.from_response(r) for r in response.products]
    return PagedResult(
        items=items,
        total=response.total,
        next_cursor=response.next_cursor,
    )
```

!!! warning "Cursor pagination limitations"
    Cursor pagination does not support jumping to arbitrary pages. Users can only navigate forward using the "Next" button. Sorting is also limited to the ordering supported by your gRPC service.

## Sorting

Django Admin's default sort controls (clicking column headers) are not supported for gRPC-backed resources because the admin cannot construct an ORDER BY clause. If your gRPC service supports sorting, pass the sort parameter through filters:

```python
class ProductAdmin(GrpcResourceAdmin):
    def get_grpc_filters(self, request):
        filters = super().get_grpc_filters(request)
        ordering = request.GET.get("o")
        if ordering:
            filters["ordering"] = ordering
        return filters
```

## list_per_page

Default items per page:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_per_page = 50
```

You can also set a global default in `settings.py`:

```python
GRPC_ADMIN = {
    "GRPC_ADMIN_DEFAULT_PAGE_SIZE": 50,
}
```

## list_max_show_all

Maximum number of items to show when the user clicks "Show all":

```python
class ProductAdmin(GrpcResourceAdmin):
    list_max_show_all = 500
```

## list_display_links

Which columns should link to the change view:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_display = ["id", "name", "price"]
    list_display_links = ["id", "name"]
```

## list_editable

!!! warning "Not supported"
    Inline editing (`list_editable`) is not supported for gRPC-backed resources because the admin cannot save changes without calling the adapter for each row.

## Actions

### Built-in Delete Action

When `grpc_enable_delete = True` and the adapter supports delete, a "Delete selected records" action appears in the dropdown.

### Custom Actions

Add custom actions just like standard Django Admin:

```python
from django.contrib import messages

class ProductAdmin(GrpcResourceAdmin):
    actions = ["activate_selected", "deactivate_selected"]

    @admin.action(description="Activate selected products")
    def activate_selected(self, request, queryset):
        adapter = self.get_adapter()
        for obj in queryset:
            adapter.update(self.resource_class, obj.pk, {"active": True})
        messages.success(request, "Selected products activated.")

    @admin.action(description="Deactivate selected products")
    def deactivate_selected(self, request, queryset):
        adapter = self.get_adapter()
        for obj in queryset:
            adapter.update(self.resource_class, obj.pk, {"active": False})
        messages.success(request, "Selected products deactivated.")
```

Because `queryset` is a `GrpcFakeQuerySet`, iterate over it to access the wrapped resource instances.

## Empty States

When the adapter returns no items or raises an error, the admin displays an empty table with a message:

> "No data found or error fetching data."

You can customize this by overriding `changelist_view` and adding your own messages.
