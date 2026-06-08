# Permissions

Permissions in django-admin-grpc work at two levels:

1. **Capability flags** — whether create, update, or delete is enabled at all
2. **Django's permission system** — `has_add_permission`, `has_change_permission`, `has_delete_permission`

Both must be satisfied for an action to be available.

## Capability Flags

Control which operations are exposed using three flags on the admin class:

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter

    grpc_enable_create = True   # show "Add" button
    grpc_enable_update = True   # allow editing in change view
    grpc_enable_delete = True   # show delete button and bulk delete action
```

!!! warning "Adapter capability is also checked"
    These flags are **ANDed** with adapter capability. If the adapter does not implement `create()`, the add view is disabled automatically even when `grpc_enable_create = True`.

    | Flag | Adapter Method | Required |
    |------|---------------|----------|
    | `grpc_enable_create` | `create()` | `grpc_form_fields` must also be set |
    | `grpc_enable_update` | `update()` | `grpc_form_fields` must also be set |
    | `grpc_enable_delete` | `delete()` | — |

## Form Fields Requirement

For create and update to work, you must also define `grpc_form_fields`:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_enable_create = True
    grpc_enable_update = True
    grpc_form_fields = ["name", "price", "active"]  # required for forms
```

Without `grpc_form_fields`, the admin cannot build a form, so create and update are disabled regardless of the flags.

## Django Permission Hooks

Override Django's standard permission methods for dynamic checks:

### has_add_permission

```python
class ProductAdmin(GrpcResourceAdmin):
    def has_add_permission(self, request):
        return (
            request.user.is_superuser
            and super().has_add_permission(request)
        )
```

### has_change_permission

By default, `has_change_permission` delegates to `has_view_permission` because the change view doubles as the detail view:

```python
def has_change_permission(self, request, obj=None):
    return self.has_view_permission(request, obj=obj)
```

If you want to restrict editing while still allowing viewing, you need a different approach — consider overriding the change view template or using `grpc_enable_update` conditionally.

### has_delete_permission

```python
class ProductAdmin(GrpcResourceAdmin):
    def has_delete_permission(self, request, obj=None):
        return request.user.groups.filter(name="Admins").exists()
```

### has_view_permission

View permission is always granted by default:

```python
def has_view_permission(self, request, obj=None):
    return True
```

Override to restrict read access:

```python
class ProductAdmin(GrpcResourceAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("catalog.view_product")
```

## Read-Only Admin

To create a completely read-only admin, set all capability flags to `False`:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_enable_create = False
    grpc_enable_update = False
    grpc_enable_delete = False
```

Users can still browse the list and view detail pages, but all edit controls are hidden.

## Permission Matrix

| Permission | Controls | Depends On |
|------------|----------|------------|
| View list | `has_view_permission` | Always `True` by default |
| View detail | `has_change_permission` | `has_view_permission` |
| Add record | `has_add_permission` | `grpc_enable_create` + adapter `create()` + `grpc_form_fields` |
| Edit record | `has_change_permission` + `_can_update()` | `grpc_enable_update` + adapter `update()` + `grpc_form_fields` |
| Delete record | `has_delete_permission` | `grpc_enable_delete` + adapter `delete()` |
| Bulk delete | `has_delete_permission` | Same as delete |

## Object-Level Permissions

django-admin-grpc does not support object-level permissions out of the box because it does not have a database table to query. If you need object-level checks, implement them in the adapter:

```python
class CatalogAdapter(BaseGrpcServiceAdapter):
    def update(self, resource_class, pk, data):
        # The gRPC service should enforce ownership checks
        try:
            return self.stub.UpdateProduct(UpdateProductRequest(id=pk, **data))
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.PERMISSION_DENIED:
                raise self._map_rpc_error(exc)
            raise
```

Then handle the `GrpcPermissionDeniedError` in the admin if you need custom behavior.
