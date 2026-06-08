# API Reference — Adapters

## `BaseGrpcServiceAdapter`

Abstract interface between Django admin and a remote gRPC service.

### Class Attributes

#### `service_name: str`

Human-readable name used by the registry.

```python
class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"
```

### Abstract Methods

#### `list(resource_class, page=1, page_size=25, filters=None) -> PagedResult`

Fetch a page of entities.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | Resource class to instantiate for each row. |
| `page` | `int` | 1-indexed page number. |
| `page_size` | `int` | Items per page. |
| `filters` | `dict \| None` | Filter dictionary from query-string. |

**Returns:** `PagedResult` with `items` and `total`.

#### `get(resource_class, pk) -> BaseGrpcResource | None`

Fetch a single entity by primary key.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | Resource class to instantiate. |
| `pk` | `str` | Primary key value. |

**Returns:** Resource instance, or `None` if not found.

### Optional Methods

#### `create(resource_class, data) -> BaseGrpcResource`

Create a new entity. Raises `NotImplementedError` by default.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | Resource class. |
| `data` | `dict` | Cleaned form data. |

**Returns:** Created resource instance.

#### `update(resource_class, pk, data) -> BaseGrpcResource`

Update an existing entity. Raises `NotImplementedError` by default.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | Resource class. |
| `pk` | `str` | Primary key. |
| `data` | `dict` | Cleaned form data. |

**Returns:** Updated resource instance.

#### `delete(resource_class, pk) -> bool`

Delete an entity. Raises `NotImplementedError` by default.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | Resource class. |
| `pk` | `str` | Primary key. |

**Returns:** `True` if deleted.

### Properties

#### `supports_create -> bool`

`True` if `create()` is implemented (not the base class stub).

#### `supports_update -> bool`

`True` if `update()` is implemented.

#### `supports_delete -> bool`

`True` if `delete()` is implemented.

### Utility Methods

#### `close() -> None`

Release any held connections. Override if needed.

#### `_wrap_channel(channel: grpc.Channel) -> grpc.Channel`

Wrap a raw gRPC channel with the trace interceptor.

```python
@property
def channel(self):
    if self._channel is None:
        raw = grpc.insecure_channel("service:50051")
        self._channel = self._wrap_channel(raw)
    return self._channel
```

#### `_trace_context_provider()`

Return the configured trace-context callable, or a no-op.

#### `_map_rpc_error(exc: grpc.RpcError) -> Exception`

Map a gRPC error to a typed `GrpcAdminError`. Callers should `raise` the result.

```python
try:
    return self.stub.Get(...)
except grpc.RpcError as exc:
    raise self._map_rpc_error(exc)
```

## `AdapterRegistry`

Central registry for adapter instances.

### Methods

#### `register(service_name: str, adapter: BaseGrpcServiceAdapter) -> None`

Register an adapter.

```python
from django_grpc_admin.registry import adapter_registry
adapter_registry.register("catalog", CatalogAdapter())
```

#### `unregister(service_name: str) -> None`

Remove a registered adapter.

#### `get_adapter(service_name: str) -> BaseGrpcServiceAdapter | None`

Get an adapter by name.

#### `list_services() -> list[str]`

Return all registered service names.

#### `clear() -> None`

Remove all adapters. Useful in tests.

## `PagedResult`

Dataclass returned by `adapter.list()`.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `items` | `list[Any]` | — | The page of resource instances. |
| `total` | `int` | `0` | Total number of items across all pages. |
| `page` | `int` | `1` | Current page number (1-indexed). |
| `page_size` | `int` | `25` | Items per page. |
| `next_cursor` | `str \| None` | `None` | Opaque cursor for cursor-based pagination. |

## `GrpcPaginator`

Paginator that uses a pre-computed total count.

### Methods

#### `__init__(object_list, per_page, total_count, **kwargs)`

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `object_list` | `list` | Items for the current page. |
| `per_page` | `int` | Items per page. |
| `total_count` | `int` | Total items across all pages. |

#### `count` (property)

Return the total count.

## `TraceClientInterceptor`

gRPC client interceptor that injects trace context and logs call latencies.

### Methods

#### `__init__(trace_context_provider=None)`

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `trace_context_provider` | `Callable[[], dict[str, str]] \| None` | Returns header dict. |

#### `intercept_unary_unary(continuation, client_call_details, request)`

Inject trace metadata and log call latency.
