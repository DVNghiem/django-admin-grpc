# Architecture

django-grpc-admin bridges Django Admin and remote gRPC services without requiring an ORM model or database table. This page explains how the pieces fit together.

## The Fake Model Pattern

Django Admin is designed around Django models. It expects `model._meta`, `model.objects`, and `model.DoesNotExist` to exist. django-grpc-admin provides a **fake model** that satisfies these expectations while fetching data from a remote service.

```
┌─────────────────────────────────────────────────────────────┐
│                    Django Admin (ModelAdmin)                 │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ List View│  │ Add View │  │ChangeView│  │DeleteView│    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │             │             │             │           │
│       └─────────────┴─────────────┴─────────────┘           │
│                         │                                    │
│              GrpcResourceAdmin                               │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Fake Model (generated at runtime)               │
│                                                              │
│  • _meta (FakeModelMeta)    • objects (GrpcFakeQuerySet)     │
│  • DoesNotExist             • MultipleObjectsReturned        │
│  • _default_manager                                            │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              BaseGrpcServiceAdapter                          │
│                                                              │
│  list()  →  get()  →  create()  →  update()  →  delete()    │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Your gRPC Service                        │
│                                                              │
│  ListProducts  GetProduct  CreateProduct                     │
│  UpdateProduct  DeleteProduct                                │
└─────────────────────────────────────────────────────────────┘
```

### Why a fake model?

Django Admin's internals rely heavily on `ModelAdmin` and its expectations around models, querysets, and fields. Rather than reimplementing all of Django Admin, django-grpc-admin creates a thin compatibility layer:

- **`FakeModelMeta`** — simulates `model._meta` with `app_label`, `model_name`, `verbose_name`, `pk`, and `get_field()`
- **`GrpcFakeQuerySet`** — a minimal queryset stand-in that supports `filter()`, `all()`, and iteration for admin actions
- **`ModelWrapper`** — wraps a `BaseGrpcResource` instance so templates can call `.pk`, `._meta`, and `.serializable_value()`

This approach means you get all of Django Admin's existing UI, URL routing, permission checks, and template rendering without writing a single database migration.

## Data Flow: Admin → Adapter → gRPC → Service

### List View

```
User opens /admin/catalog/product/
        │
        ▼
GrpcResourceAdmin.changelist_view()
        │
        ▼
GrpcChangeList.get_results()
        │
        ├──► get_grpc_filters(request)  →  {active: "1"}
        │
        └──► fetch_list(page=1, page_size=25, filters={active: "1"})
                    │
                    ▼
            adapter.list(Product, page=1, page_size=25, filters={active: "1"})
                    │
                    ▼
            gRPC call: ListProductsRequest(active="1", page=1, page_size=25)
                    │
                    ▼
            PagedResult(items=[...], total=100)
                    │
                    ▼
            ModelWrapper(instance, fake_meta) for each item
                    │
                    ▼
            Rendered in admin list template
```

### Add View

```
User submits the Add Product form
        │
        ▼
GrpcResourceAdmin.add_view()
        │
        ├──► _build_form_class()  →  validates POST data
        │
        └──► adapter.create(Product, cleaned_data)
                    │
                    ▼
            gRPC call: CreateProductRequest(name="...", price=...)
                    │
                    ▼
            Returns new Product instance
                    │
                    ▼
            Redirect to changelist with success message
```

### Change View

```
User edits a product and clicks Save
        │
        ▼
GrpcResourceAdmin.change_view()
        │
        ├──► fetch_one(pk)  →  gets current data for display
        │
        ├──► _build_form_class()  →  validates POST data
        │
        └──► adapter.update(Product, pk, cleaned_data)
                    │
                    ▼
            gRPC call: UpdateProductRequest(id=pk, name="...", price=...)
                    │
                    ▼
            Returns updated Product instance
                    │
                    ▼
            Redirect with success message
```

### Delete View

```
User confirms deletion
        │
        ▼
GrpcResourceAdmin.delete_view()
        │
        └──► adapter.delete(Product, pk)
                    │
                    ▼
            gRPC call: DeleteProductRequest(id=pk)
                    │
                    ▼
            Redirect to changelist
```

## Component Overview

| Component | Role | File |
|-----------|------|------|
| `BaseGrpcResource` | Declares the schema of a remote entity | `resources.py` |
| `BaseFieldConfig` | Base class for field metadata; use concrete subclasses like `CharFieldConfig`, `IntegerFieldConfig`, etc. | `resources.py` |
| `BaseGrpcServiceAdapter` | Transport layer between admin and gRPC | `adapters.py` |
| `GrpcResourceAdmin` | `ModelAdmin` subclass that uses the adapter | `admin.py` |
| `FakeModelMeta` | Stand-in for `model._meta` | `models.py` |
| `GrpcFakeQuerySet` | Stand-in for `QuerySet` | `models.py` |
| `ModelWrapper` | Wraps resource instances for template compatibility | `models.py` |
| `FormBuilder` | Builds Django forms from field config lists | `forms.py` |
| `PagedResult` | Dataclass returned by `adapter.list()` | `paginator.py` |
| `GrpcPaginator` | Paginator that uses the total count from the service | `paginator.py` |
| `AdapterRegistry` | Central registry for adapters by service name | `registry.py` |

## Design Decisions

### Why not use a real Django model with `managed = False`?

A `managed = False` model still requires a database connection and expects to run SQL queries. django-grpc-admin is designed for services where there is no database access at all — the data lives entirely in a remote microservice.

### Why separate resources, adapters, and admin classes?

This three-layer separation keeps concerns clean:

- **Resources** know the schema (what fields exist)
- **Adapters** know the transport (how to call the gRPC service)
- **Admin classes** know the presentation (which fields to show, which filters to render)

You can reuse the same resource with different adapters (e.g. a real gRPC adapter in production and an in-memory adapter for tests). You can also reuse the same adapter for multiple resources if the gRPC service supports multiple entity types.

### Why use a registry instead of direct adapter references?

The `AdapterRegistry` is optional. You can set `adapter_class` directly on the admin class. The registry is useful when:

- Multiple admin classes share the same adapter
- You want to initialize adapters once at startup (e.g. in `AppConfig.ready()`)
- You need to swap adapters at runtime (e.g. for testing)

## Error Handling Flow

```
gRPC service returns an error
        │
        ▼
adapter catches grpc.RpcError
        │
        ▼
adapter._map_rpc_error(exc)  →  typed GrpcAdminError
        │
        ▼
admin view catches GrpcAdminError
        │
        ▼
Renders as Django message (error / warning / success)
```

See [Error Handling](../api/exceptions.md) for the full exception hierarchy and status code mapping.
