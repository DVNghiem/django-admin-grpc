# Migration Guide

This guide helps you migrate from a custom in-project gRPC admin implementation to the reusable `django-admin-grpc` package.

## What You Are Replacing

If your project has code like this:

- A custom `GrpcModelAdmin` base class
- Dataclasses with inline `fields_meta` dicts
- A `GrpcServiceClient` that mixes stubs, data classes, and CRUD logic
- Manual `admin.site._registry` manipulation
- Inline form builders, fake models, and paginators

Then you can replace all of that with `django-admin-grpc`.

## Before and After

### Resource Definition

**Before:**

```python
from dataclasses import dataclass
from core.grpc_admin.base import GrpcDataClass

@dataclass
class NetworkRule(GrpcDataClass):
    rule_id: str
    name: str
    active: bool

    class Meta:
        fields_meta = {
            'rule_id': {'type': 'char', 'label': 'Rule ID'},
            'name': {'type': 'char', 'label': 'Name'},
            'active': {'type': 'boolean', 'label': 'Active'},
        }

    @property
    def pk(self) -> str:
        return self.rule_id
```

**After:**

```python
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
)

class NetworkRule(BaseGrpcResource):
    class Meta:
        app_label = "network"
        model_name = "networkrule"
        verbose_name = "Network Rule"
        pk_field = "rule_id"

    fields = [
        CharFieldConfig(name="rule_id", label="Rule ID"),
        CharFieldConfig(name="name", label="Name"),
        BooleanFieldConfig(name="active", label="Active"),
    ]
```

### Adapter (Client)

**Before:**

```python
from core.grpc_admin.client import GrpcServiceClient

class NetworkRulesGrpcClient(GrpcServiceClient):
    SERVICE_MAP = {NetworkRule: 'rule'}
    # 500+ lines mixed stubs, data, CRUD
```

**After:**

```python
from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult

class NetworkRulesAdapter(BaseGrpcServiceAdapter):
    service_name = "network_rules"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        # gRPC call
        return PagedResult(items=items, total=total)

    def get(self, resource_class, pk):
        # gRPC call
        return resource_class(**response_dict)

    def create(self, resource_class, data):
        # gRPC call
        return resource_class(**response_dict)

    def update(self, resource_class, pk, data):
        # gRPC call
        return resource_class(**response_dict)

    def delete(self, resource_class, pk):
        # gRPC call
        return True
```

### Admin Registration

**Before:**

```python
from core.grpc_admin import GrpcModelAdmin, grpc_client_registry

_network_grpc_client = NetworkRulesGrpcClient()
grpc_client_registry.register('network_rules', _network_grpc_client)

class NetworkRuleAdmin(GrpcModelAdmin):
    service_name = 'network_rules'
    data_class = NetworkRule
    app_label = 'network'
    model_name = 'networkrule'
    verbose_name = 'Network Rule'

_network_rule_admin = NetworkRuleAdmin(admin_site=admin.site)
admin.site._registry[_network_rule_admin._fake_model] = _network_rule_admin
```

**After:**

```python
from django.contrib import admin
from django_admin_grpc.admin import GrpcResourceAdmin

@admin.register(NetworkRule.admin_model())
class NetworkRuleAdmin(GrpcResourceAdmin):
    resource_class = NetworkRule
    adapter_class = NetworkRulesAdapter
```

## Key Changes

| Concern | Before | After |
|---------|--------|-------|
| **Meta fields** | Inline dict `fields_meta` on dataclass | Declarative field config list on resource |
| **Admin registration** | Manual `admin.site._registry[...] = ...` | Standard `@admin.register(Model.admin_model())` |
| **Fake model** | Built inside `GrpcModelAdmin.__init__` | `Model.admin_model()` factory on resource class |
| **Client / data coupling** | Single file mixing stubs + data + CRUD | Separated `resources.py`, `adapters.py`, `admin.py` |
| **PK property** | `@property def pk` on every dataclass | `Meta.pk_field` on resource class |
| **Filter config** | String list, custom `get_grpc_filters` override | `grpc_filter_config` list or dict on admin class |
| **Form fields** | Implicit from `fields_meta` | Explicit `grpc_form_fields` on admin class |
| **Registry** | Global mutable `grpc_client_registry` | Optional; can use `adapter_class` directly |

## Migration Checklist

- [ ] Install `django-admin-grpc`: `pip install django-admin-grpc`
- [ ] Add `"django_admin_grpc"` to `INSTALLED_APPS`
- [ ] Convert each `GrpcDataClass` → `BaseGrpcResource` with specific field config classes
- [ ] Convert each `GrpcServiceClient` → `BaseGrpcServiceAdapter`
- [ ] Move admin classes to use `GrpcResourceAdmin` + `@admin.register(...)`
- [ ] Update any custom `change_view` / `get_grpc_filters` overrides to match new API
- [ ] Verify templates load from `django_admin_grpc/templates/`
- [ ] Remove old `core/grpc_admin/` code from your project
- [ ] Run admin smoke tests to confirm list / detail / create / update / delete

## Troubleshooting

### "No gRPC adapter available"

Check that `adapter_class` or `service_name` is set on the admin class, and that the adapter is registered in the registry if using `service_name`.

### "Object does not exist" on every record

Verify that `Meta.pk_field` on the resource matches the primary key field returned by your gRPC service.

### Filters not appearing

Ensure `grpc_filter_config` is set on the admin class, not just `list_filter`.

### Forms show no fields

`grpc_form_fields` must be set on the admin class for forms to render.

### Custom templates not loading

Template resolution order is: admin class attribute → resource Meta → `GRPC_ADMIN` setting → package default. Check that your custom template path is correct and that the template exists in a directory known to Django's template loaders.
