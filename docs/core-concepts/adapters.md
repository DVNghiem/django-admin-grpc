# Adapters

An **adapter** is the transport layer between Django Admin and your gRPC service. It implements the CRUD operations that the admin calls when users list, view, create, update, or delete records.

## BaseGrpcServiceAdapter

Subclass `BaseGrpcServiceAdapter` and implement at least `list()` and `get()`. Implement `create()`, `update()`, and `delete()` only if you need write access.

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult
import grpc

class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def __init__(self):
        self._channel = None

    @property
    def channel(self):
        if self._channel is None:
            self._channel = self._create_channel("catalog-service:50051")
        return self._channel

    def list(self, resource_class, page=1, page_size=25, filters=None):
        stub = CatalogStub(self.channel)
        request = ListProductsRequest(page=page, page_size=page_size)
        response = stub.ListProducts(request)
        items = [resource_class.from_response(r) for r in response.products]
        return PagedResult(items=items, total=response.total)

    def get(self, resource_class, pk):
        stub = CatalogStub(self.channel)
        response = stub.GetProduct(GetProductRequest(id=pk))
        return resource_class.from_response(response)

    def create(self, resource_class, data):
        stub = CatalogStub(self.channel)
        request = CreateProductRequest(**data)
        response = stub.CreateProduct(request)
        return resource_class.from_response(response)

    def update(self, resource_class, pk, data):
        stub = CatalogStub(self.channel)
        request = UpdateProductRequest(id=pk, **data)
        response = stub.UpdateProduct(request)
        return resource_class.from_response(response)

    def delete(self, resource_class, pk):
        stub = CatalogStub(self.channel)
        stub.DeleteProduct(DeleteProductRequest(id=pk))
        return True
```

### Required Methods

#### `list(resource_class, page=1, page_size=25, filters=None)`

Fetch a page of entities.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class to instantiate for each row. |
| `page` | `int` | 1-indexed page number. |
| `page_size` | `int` | Items per page. |
| `filters` | `dict \| None` | Filter dictionary from query-string parameters. |

**Returns:** `PagedResult` containing `items` and `total`.

```python
def list(self, resource_class, page=1, page_size=25, filters=None):
    # Call your gRPC list endpoint
    response = self.stub.ListProducts(...)
    items = [resource_class.from_response(r) for r in response.products]
    return PagedResult(items=items, total=response.total)
```

#### `get(resource_class, pk)`

Fetch a single entity by primary key.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class to instantiate. |
| `pk` | `str` | Primary key value. |

**Returns:** A resource instance, or `None` if not found.

```python
def get(self, resource_class, pk):
    response = self.stub.GetProduct(GetProductRequest(id=pk))
    return resource_class.from_response(response)
```

### Optional Methods

#### `create(resource_class, data)`

Create a new entity. If not implemented, the "Add" button is hidden.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `data` | `dict` | Cleaned form data. |

**Returns:** The created resource instance.

#### `update(resource_class, pk, data)`

Update an existing entity. If not implemented, the change form is read-only.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `pk` | `str` | Primary key of the entity to update. |
| `data` | `dict` | Cleaned form data. |

**Returns:** The updated resource instance.

#### `delete(resource_class, pk)`

Delete an entity. If not implemented, the delete action is hidden.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `pk` | `str` | Primary key of the entity to delete. |

**Returns:** `True` if deleted, `False` otherwise.

### Capability Properties

The adapter exposes boolean properties so the admin can check what operations are available:

| Property | Description |
|----------|-------------|
| `supports_create` | `True` if `create()` is implemented. |
| `supports_update` | `True` if `update()` is implemented. |
| `supports_delete` | `True` if `delete()` is implemented. |

### Utility Methods

#### `_wrap_channel(channel)`

Wraps a raw gRPC channel with the trace interceptor. Prefer using `_create_channel()`
in your channel property so metadata is injected into every call and the raw
channel is closed automatically if wrapping fails.

```python
@property
def channel(self):
    if self._channel is None:
        self._channel = self._create_channel("service:50051")
    return self._channel
```

!!! warning "Do not double-wrap"
    Only call `_wrap_channel()` inside the `if self._channel is None:` guard. Double-wrapping a channel will cause duplicate trace headers.

#### `_map_rpc_error(exc)`

Maps a `grpc.RpcError` to a typed `GrpcAdminError`. Callers should `raise` the result.

```python
from django_admin_grpc.exceptions import map_grpc_error

def get(self, resource_class, pk):
    try:
        return self.stub.Get(...)
    except grpc.RpcError as exc:
        raise self._map_rpc_error(exc)
```

## Adapter Registry

The `AdapterRegistry` is a central place to register and look up adapter instances by a short service name.

### Registering an adapter

```python
from django_admin_grpc.registry import adapter_registry
from myapp.adapters import CatalogAdapter

adapter = CatalogAdapter()
adapter_registry.register("catalog", adapter)
```

### Using a registered adapter in admin

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    service_name = "catalog"  # looks up in registry
```

### Direct adapter reference (no registry)

You can skip the registry and set `adapter_class` directly:

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter  # class or instance
```

### Registry API

```python
from django_admin_grpc.registry import adapter_registry

# Register
adapter_registry.register("catalog", adapter)

# Retrieve
adapter = adapter_registry.get_adapter("catalog")

# List all services
services = adapter_registry.list_services()  # ["catalog", "orders"]

# Unregister
adapter_registry.unregister("catalog")

# Clear all (useful in tests)
adapter_registry.clear()
```

## Writing a Production-Ready Adapter

### Connection Management

Create the gRPC channel lazily and reuse it across calls. gRPC channels are designed to be long-lived.

```python
class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def __init__(self):
        self._channel = None
        self._stub = None

    @property
    def channel(self):
        if self._channel is None:
            self._channel = self._create_channel(self._target)
        return self._channel

    @property
    def stub(self):
        if self._stub is None:
            self._stub = CatalogStub(self.channel)
        return self._stub

### Error Handling

Always map gRPC errors to typed exceptions so the admin can display appropriate messages.

```python
def get(self, resource_class, pk):
    try:
        response = self.stub.GetProduct(GetProductRequest(id=pk))
        return resource_class.from_response(response)
    except grpc.RpcError as exc:
        raise self._map_rpc_error(exc)
```

### Filtering

The `filters` dict contains query-string parameters. Map them to your gRPC request fields.

```python
def list(self, resource_class, page=1, page_size=25, filters=None):
    filters = filters or {}
    request = ListProductsRequest(
        page=page,
        page_size=page_size,
        active=filters.get("active"),
        search=filters.get("search"),
    )
    response = self.stub.ListProducts(request)
    ...
```

### In-Memory Adapters for Testing

For local development or integration tests, you can write an adapter that stores data in memory instead of calling a real gRPC service.

See the `example/` directory in this repository for a complete in-memory adapter implementation.
