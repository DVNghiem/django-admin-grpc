# Examples

## Example 1: Product Catalog

A complete example of a product catalog backed by a gRPC service.

```python
# catalog/resources.py
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    FloatFieldConfig,
    FKFieldConfig,
    TextFieldConfig,
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
        TextFieldConfig(name="description", required=False),
        FloatFieldConfig(name="price"),
        BooleanFieldConfig(name="active", initial=True),
        FKFieldConfig(
            name="category_id",
            label="Category",
            model="catalog.Category",
            display_field="name",
            required=False,
        ),
    ]


# catalog/adapters.py
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
            raw = grpc.insecure_channel("catalog-service:50051")
            self._channel = self._wrap_channel(raw)
        return self._channel

    def list(self, resource_class, page=1, page_size=25, filters=None):
        # ... gRPC call ...
        return PagedResult(items=[], total=0)

    def get(self, resource_class, pk):
        # ... gRPC call ...
        return resource_class(id=pk, name="Widget")

    def create(self, resource_class, data):
        # ... gRPC call ...
        return resource_class(**data)

    def update(self, resource_class, pk, data):
        # ... gRPC call ...
        return resource_class(pk=pk, **data)

    def delete(self, resource_class, pk):
        # ... gRPC call ...
        return True


# catalog/admin.py
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin
from .resources import Product
from .adapters import CatalogAdapter

@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    list_display = ["id", "name", "price", "active"]
    list_filter = ["active"]
    search_fields = ["name", "description"]

    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "description", "price", "active", "category_id"]
```

## Example 2: Read-Only Dashboard

Display data from a reporting service without allowing edits.

```python
from django_admin_grpc.resources import (
    BaseGrpcResource,
    CharFieldConfig,
    DateFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
)

class SalesReport(BaseGrpcResource):
    class Meta:
        app_label = "analytics"
        model_name = "salesreport"
        verbose_name = "Sales Report"
        pk_field = "report_id"

    fields = [
        CharFieldConfig(name="report_id"),
        DateFieldConfig(name="date"),
        CharFieldConfig(name="region"),
        FloatFieldConfig(name="revenue"),
        IntegerFieldConfig(name="orders"),
    ]

class SalesReportAdmin(GrpcResourceAdmin):
    resource_class = SalesReport
    adapter_class = AnalyticsAdapter

    list_display = ["report_id", "date", "region", "revenue", "orders"]
    list_filter = ["region"]
    search_fields = ["region"]

    # Read-only
    grpc_enable_create = False
    grpc_enable_update = False
    grpc_enable_delete = False
```

## Example 3: Network Rules with gRPC FK Resolution

Link to another gRPC service for foreign key resolution.

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
        pk_field = "rule_id"

    fields = [
        CharFieldConfig(name="rule_id", label="Rule ID"),
        CharFieldConfig(name="name"),
        FKFieldConfig(
            name="partner_id",
            label="Partner",
            service="partners",
            get_method="get_partner",
            display_field="name",
        ),
        IntegerFieldConfig(name="priority"),
        BooleanFieldConfig(name="active", initial=True),
    ]

class NetworkRuleAdmin(GrpcResourceAdmin):
    resource_class = NetworkRule
    adapter_class = NetworkRulesAdapter

    list_display = ["rule_id", "name", "partner_id", "priority", "active"]
    grpc_enable_create = True
    grpc_enable_update = True
    grpc_enable_delete = True
    grpc_form_fields = ["name", "partner_id", "priority", "active"]
```

## Example 4: Custom Adapter with Authentication

Pass authentication tokens to the gRPC service.

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter

class SecureCatalogAdapter(BaseGrpcServiceAdapter):
    service_name = "catalog"

    def __init__(self, auth_token):
        self.auth_token = auth_token
        self._channel = None

    @property
    def channel(self):
        if self._channel is None:
            creds = grpc.ssl_channel_credentials()
            self._channel = grpc.secure_channel("catalog-service:443", creds)
        return self._channel

    def _metadata(self):
        return [("authorization", f"Bearer {self.auth_token}")]

    def list(self, resource_class, page=1, page_size=25, filters=None):
        stub = CatalogStub(self.channel)
        request = ListProductsRequest(page=page, page_size=page_size)
        response = stub.ListProducts(request, metadata=self._metadata())
        items = [resource_class.from_response(r) for r in response.products]
        return PagedResult(items=items, total=response.total)
```

Register with the registry in your `AppConfig.ready()`:

```python
# catalog/apps.py
from django.apps import AppConfig

class CatalogConfig(AppConfig):
    name = "catalog"

    def ready(self):
        from django_admin_grpc.registry import adapter_registry
        from .adapters import SecureCatalogAdapter

        token = get_service_account_token()  # your auth logic
        adapter = SecureCatalogAdapter(token)
        adapter_registry.register("catalog", adapter)
```

## Example 5: In-Memory Adapter for Testing

Useful for local development or integration tests.

```python
class InMemoryAdapter(BaseGrpcServiceAdapter):
    service_name = "test"
    _store: dict[str, dict] = {}

    def list(self, resource_class, page=1, page_size=25, filters=None):
        items = list(self._store.values())
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]
        return PagedResult(
            items=[resource_class(**item) for item in page_items],
            total=total,
        )

    def get(self, resource_class, pk):
        data = self._store.get(str(pk))
        if data:
            return resource_class(**data)
        return None

    def create(self, resource_class, data):
        pk = str(uuid.uuid4())
        record = dict(data)
        record["id"] = pk
        self._store[pk] = record
        return resource_class(**record)

    def update(self, resource_class, pk, data):
        record = self._store.get(str(pk))
        if record:
            record.update(data)
            return resource_class(**record)
        return None

    def delete(self, resource_class, pk):
        return self._store.pop(str(pk), None) is not None
```

## Example 6: Multiple Resources, One Adapter

When a single gRPC service manages multiple entity types:

```python
class InventoryAdapter(BaseGrpcServiceAdapter):
    service_name = "inventory"

    def _get_stub(self, resource_class):
        if resource_class.__name__ == "Warehouse":
            return WarehouseStub(self.channel)
        if resource_class.__name__ == "StockItem":
            return StockStub(self.channel)
        raise ValueError(f"Unknown resource: {resource_class}")

    def list(self, resource_class, page=1, page_size=25, filters=None):
        stub = self._get_stub(resource_class)
        # ... dispatch to correct stub method ...
```

## Example 7: Running the Example Project

The repository includes a working example project in the `example/` directory:

```bash
cd example
python manage.py migrate
python manage.py runserver
```

Browse to `/admin/` to see Products and Categories backed by in-memory adapters.
