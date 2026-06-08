# API Reference — Exceptions

## Exception Hierarchy

```
Exception
└── GrpcAdminError
    ├── GrpcNotFoundError
    ├── GrpcPermissionDeniedError
    ├── GrpcInvalidArgumentError
    ├── GrpcUnavailableError
    └── GrpcDeadlineExceededError
```

## `GrpcAdminError`

Base exception for all django-admin-grpc errors.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `message` | `str` | — | Human-readable error message. |
| `code` | `str \| None` | `None` | Error code string. |
| `grpc_code` | `grpc.StatusCode \| None` | `None` | Original gRPC status code. |
| `details` | `str \| None` | `None` | Additional error details. |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `message` | `str` | Error message. |
| `code` | `str \| None` | Error code. |
| `grpc_code` | `grpc.StatusCode \| None` | gRPC status code. |
| `details` | `str \| None` | Error details. |

### Methods

#### `__str__() -> str`

Returns `message` with optional `code` and `grpc_code` annotations.

```python
>>> str(GrpcAdminError("Product not found", code="NOT_FOUND"))
'Product not found (code=NOT_FOUND)'
```

## `GrpcNotFoundError`

The requested resource was not found on the gRPC service.

**Mapped from:** `grpc.StatusCode.NOT_FOUND`

**Admin behavior:** Redirects to the "object does not exist" page.

## `GrpcPermissionDeniedError`

The caller does not have permission to perform this action.

**Mapped from:** `grpc.StatusCode.PERMISSION_DENIED`, `grpc.StatusCode.UNAUTHENTICATED`

**Admin behavior:** Shown as a red error message; user stays on the page.

## `GrpcInvalidArgumentError`

One or more arguments are invalid.

**Mapped from:** `grpc.StatusCode.INVALID_ARGUMENT`

**Admin behavior:** Shown as a red error message (validation failed).

## `GrpcUnavailableError`

The gRPC service is currently unavailable.

**Mapped from:** `grpc.StatusCode.UNAVAILABLE`

**Admin behavior:** Shown as a red error message (service down).

## `GrpcDeadlineExceededError`

The gRPC call deadline was exceeded before completion.

**Mapped from:** `grpc.StatusCode.DEADLINE_EXCEEDED`

**Admin behavior:** Shown as a red error message (timeout).

## `map_grpc_error(exc: grpc.RpcError) -> GrpcAdminError`

Map a `grpc.RpcError` to the appropriate `GrpcAdminError` subclass.

### Mapping Table

| gRPC Status Code | Exception Class | Admin Behavior |
|------------------|-----------------|----------------|
| `NOT_FOUND` | `GrpcNotFoundError` | Redirect to "object does not exist" |
| `PERMISSION_DENIED` | `GrpcPermissionDeniedError` | Red error message |
| `UNAUTHENTICATED` | `GrpcPermissionDeniedError` | Red error message |
| `INVALID_ARGUMENT` | `GrpcInvalidArgumentError` | Red error message |
| `UNAVAILABLE` | `GrpcUnavailableError` | Red error message |
| `DEADLINE_EXCEEDED` | `GrpcDeadlineExceededError` | Red error message |
| Other | `GrpcAdminError` | Generic red error message |

### Usage in Adapters

```python
from django_admin_grpc.exceptions import map_grpc_error

class MyAdapter(BaseGrpcServiceAdapter):
    def get(self, resource_class, pk):
        try:
            return self.stub.GetProduct(GetProductRequest(id=pk))
        except grpc.RpcError as exc:
            raise self._map_rpc_error(exc)
```

### Catching Typed Exceptions

```python
from django_admin_grpc.exceptions import GrpcNotFoundError, GrpcPermissionDeniedError

class ProductAdmin(GrpcResourceAdmin):
    def change_view(self, request, object_id, ...):
        try:
            return super().change_view(request, object_id, ...)
        except GrpcNotFoundError:
            messages.error(request, "Product was deleted remotely.")
            return HttpResponseRedirect(reverse("admin:catalog_product_changelist"))
        except GrpcPermissionDeniedError:
            messages.error(request, "You don't have permission to edit this product.")
            return HttpResponseRedirect(request.path)
```
