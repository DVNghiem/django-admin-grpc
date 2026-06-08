# django-admin-grpc

**Django Admin backed by gRPC services — no ORM required.**

Use django-admin-grpc to expose remote microservices inside Django Admin with full list, create, update, delete, and search support. You define a resource schema, wire a gRPC adapter, and register a single admin class — the package handles forms, pagination, filtering, and error mapping for you.

## Key Features

- **No ORM required** — works with any gRPC service, regardless of data store
- **Standard Django Admin interface** — your team uses the same familiar UI
- **Declarative resource schemas** — define fields with specific field config classes instead of models
- **Full CRUD support** — list, create, update, delete, and bulk operations
- **Built-in filtering and search** — sidebar filters and text search work out of the box
- **Foreign key resolution** — link to Django ORM models or other gRPC services
- **Error mapping** — gRPC errors become user-friendly Django messages
- **Pagination** — offset or cursor-based, configurable per resource
- **Customizable forms and widgets** — override any field's widget or the entire form
- **Trace interceptor** — inject request IDs and trace headers into every gRPC call

## When to Use django-admin-grpc

Use this package when you want to manage data from a remote service through Django Admin. Common scenarios include:

| Scenario | Example |
|----------|---------|
| Microservice administration | Managing products in a catalog service |
| Cross-service data views | Displaying network rules from a policy engine |
| Legacy system integration | Administering data in a service you cannot modify |
| Read-only dashboards | Viewing analytics data from a reporting service |
| Mixed ORM + gRPC stacks | Some models in Postgres, some entities in a remote service |

!!! tip "Not sure if it's the right fit?"
    If your data already lives in a Django-managed database, use Django's built-in `ModelAdmin`. If your data lives in a remote service accessible via gRPC, use django-admin-grpc.

## Quick Example

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


# adapters.py
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult

class CatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        items = [...]  # call your gRPC List endpoint
        return PagedResult(items=items, total=100)

    def get(self, resource_class, pk):
        data = ...  # call your gRPC Get endpoint
        return resource_class(**data)

    def create(self, resource_class, data):
        ...

    def update(self, resource_class, pk, data):
        ...

    def delete(self, resource_class, pk):
        ...


# admin.py
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin

from .resources import Product
from .adapters import CatalogAdapter

@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    list_display = ["id", "name", "price", "active"]
    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "price", "active"]
```

That is all. Django Admin now shows list, add, change, and delete screens powered by your gRPC service.

## Next Steps

- Follow the [Installation](getting-started/installation.md) guide to set up the package
- Walk through the [Quick Start](getting-started/quickstart.md) tutorial for a complete working example
- Learn about [Architecture](core-concepts/architecture.md) to understand how the pieces fit together
- Browse the [Admin Guide](admin-guide/list-views.md) for configuration options
