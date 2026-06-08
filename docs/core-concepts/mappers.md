# Mappers

A **mapper** translates between Django form data and gRPC request/response messages. While adapters handle transport, mappers handle the shape of the data.

## When to Use a Mapper

You need a custom mapper when:

- Your gRPC request messages do not match your resource field names
- You need to transform data before sending it to the gRPC service (e.g. string IDs to enum values)
- You need to parse complex protobuf responses into resource instances
- You want to centralize data transformation logic outside the adapter

If your gRPC service uses plain dictionaries and field names match 1-to-1, you can skip mappers entirely — the `DefaultGrpcMapper` handles this case automatically.

## BaseGrpcMapper

Subclass `BaseGrpcMapper` and implement the transformation methods:

```python
from django_admin_grpc.mappers import BaseGrpcMapper

class ProductMapper(BaseGrpcMapper):
    def to_create_request(self, resource_class, cleaned_data):
        return CreateProductRequest(
            name=cleaned_data["name"],
            price=int(cleaned_data["price"] * 100),  # dollars → cents
            active=cleaned_data["active"],
        )

    def to_update_request(self, resource_class, pk, cleaned_data):
        return UpdateProductRequest(
            id=pk,
            name=cleaned_data["name"],
            price=int(cleaned_data["price"] * 100),
            active=cleaned_data["active"],
        )

    def from_response(self, resource_class, response):
        return resource_class(
            id=response.id,
            name=response.name,
            price=response.price / 100.0,  # cents → dollars
            active=response.active,
        )

    def to_list_request(self, resource_class, page, page_size, filters):
        return ListProductsRequest(
            page=page,
            page_size=page_size,
            search=filters.get("search", ""),
        )

    def from_list_response(self, resource_class, response):
        return {
            "items": [self.from_response(resource_class, r) for r in response.products],
            "total": response.total,
            "next_cursor": getattr(response, "next_cursor", None),
        }
```

### Methods

#### `to_create_request(resource_class, cleaned_data)`

Convert form `cleaned_data` into a gRPC *Create* request message.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `cleaned_data` | `dict` | Validated form data. |

**Returns:** A protobuf message instance or plain dict.

#### `to_update_request(resource_class, pk, cleaned_data)`

Convert form `cleaned_data` into a gRPC *Update* request message.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `pk` | `str` | Primary key of the entity being updated. |
| `cleaned_data` | `dict` | Validated form data. |

**Returns:** A protobuf message instance or plain dict.

#### `from_response(resource_class, response)`

Convert a gRPC response message into a `BaseGrpcResource` instance.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `response` | `Any` | gRPC response message. |

**Returns:** A resource instance.

#### `to_list_request(resource_class, page, page_size, filters)`

Convert list parameters into a gRPC *List* request message.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `page` | `int` | 1-indexed page number. |
| `page_size` | `int` | Items per page. |
| `filters` | `dict \| None` | Filter dictionary. |

**Returns:** A protobuf message instance or plain dict.

#### `from_list_response(resource_class, response)`

Convert a gRPC *List* response into a dict with keys `items`, `total`, and `next_cursor`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | The resource class. |
| `response` | `Any` | gRPC list response message. |

**Returns:** `dict` with `items`, `total`, `next_cursor`.

## DefaultGrpcMapper

The built-in mapper assumes the adapter works with plain dicts and that `resource_class.from_response()` can handle the response.

```python
from django_admin_grpc.mappers import DefaultGrpcMapper

mapper = DefaultGrpcMapper()
```

Behavior:

- `to_create_request` returns `cleaned_data` as-is
- `to_update_request` returns `{"pk": pk, **cleaned_data}`
- `from_response` delegates to `resource_class.from_response()`
- `to_list_request` returns `{"page": page, "page_size": page_size, "filters": filters}`
- `from_list_response` extracts `items`, `total`, `next_cursor` from the response

## Using a Mapper in an Adapter

The mapper is used inside the adapter methods:

```python
class CatalogAdapter(BaseGrpcServiceAdapter):
    def __init__(self):
        self.mapper = ProductMapper()

    def list(self, resource_class, page=1, page_size=25, filters=None):
        request = self.mapper.to_list_request(resource_class, page, page_size, filters)
        response = self.stub.ListProducts(request)
        return self.mapper.from_list_response(resource_class, response)

    def create(self, resource_class, data):
        request = self.mapper.to_create_request(resource_class, data)
        response = self.stub.CreateProduct(request)
        return self.mapper.from_response(resource_class, response)
```

## Example: Enum Mapping

When your gRPC service uses enum values but your admin uses human-readable strings:

```python
STATUS_MAP = {
    "draft": ProductStatus.DRAFT,
    "published": ProductStatus.PUBLISHED,
    "archived": ProductStatus.ARCHIVED,
}

class ProductMapper(BaseGrpcMapper):
    def to_create_request(self, resource_class, cleaned_data):
        data = dict(cleaned_data)
        data["status"] = STATUS_MAP[data["status"]]
        return CreateProductRequest(**data)

    def from_response(self, resource_class, response):
        return resource_class(
            id=response.id,
            name=response.name,
            status=response.status.name.lower(),
        )
```

## Example: Nested Messages

When your gRPC request has nested structures:

```python
class OrderMapper(BaseGrpcMapper):
    def to_create_request(self, resource_class, cleaned_data):
        return CreateOrderRequest(
            customer_id=cleaned_data["customer_id"],
            items=[
                OrderItem(product_id=item["product_id"], quantity=item["qty"])
                for item in cleaned_data["items"]
            ],
        )
```
