# Resources

A **resource** in django-grpc-admin is a Python class that describes the shape of a remote entity. It tells Django Admin what columns exist, what types they are, and which field serves as the primary key.

## BaseGrpcResource

Subclass `BaseGrpcResource` and define:

- `Meta` class with `app_label` and optionally `model_name`, `verbose_name`, `pk_field`
- `fields` — a list of field config objects

```python
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
        verbose_name_plural = "Products"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id", label="ID"),
        CharFieldConfig(name="name", label="Name", max_length=200),
        FloatFieldConfig(name="price", label="Price"),
        BooleanFieldConfig(name="active", label="Active", initial=True),
    ]
```

### Meta Options

| Option | Default | Description |
|--------|---------|-------------|
| `app_label` | `""` | Used for URL reversing and app grouping in the admin index. **Required.** |
| `model_name` | `""` | Machine-friendly name (used in URLs). Defaults to lowercase class name. |
| `verbose_name` | `""` | Human-readable singular name. Defaults to title-cased `model_name`. |
| `verbose_name_plural` | `""` | Human-readable plural name. Defaults to `verbose_name + "s"`. |
| `pk_field` | `"id"` | Name of the primary key field. |
| `change_form_template` | `""` | Custom template for add/change views. |
| `delete_confirm_template` | `""` | Custom template for delete confirmation. |

!!! tip "app_label is required"
    Without `app_label`, URL reversing and admin grouping will not work correctly. Always set it to match your Django app's name.

## Field Configuration

Field config classes are dataclasses that hold metadata for a single field. All share a common base (`BaseFieldConfig`) and add type-specific attributes.

```python
from django_admin_grpc.resources import FKFieldConfig

FKFieldConfig(
    name="category_id",
    label="Category",
    model="catalog.Category",
    display_field="name",
    required=False,
)
```

### Common Parameters

All field config subclasses accept these parameters:

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `str` | — | Field identifier. **Required.** |
| `label` | `str \| None` | auto | Human label. Defaults to title-cased `name`. |
| `required` | `bool` | `True` | Whether the form field is required. |
| `help_text` | `str` | `""` | Help text shown below the form field. |
| `initial` | `Any` | `None` | Default value for the form field. |
| `source` | `str \| None` | `None` | Attribute name in the gRPC response if it differs from `name`. |

### Supported Field Types

| Class | `type` | Form Widget | Notes |
|-------|--------|-------------|-------|
| `CharFieldConfig` | `char` | `TextInput` | Use `max_length` to limit input. |
| `TextFieldConfig` | `text` | `Textarea` | Multi-line text. |
| `IntegerFieldConfig` | `integer` | `NumberInput` | Whole numbers. |
| `FloatFieldConfig` | `float` | `NumberInput` | Decimal numbers. |
| `BooleanFieldConfig` | `boolean` | `CheckboxInput` | Defaults to `False` unless `initial=True`. |
| `ChoicesFieldConfig` | `choices` | `Select` | Provide `choices=[("a", "A"), ...]`. |
| `FKFieldConfig` | `fk` | `Select` | Use `model` for Django lookups or `service` for gRPC lookups. |
| `DateFieldConfig` | `date` | `DateInput` | Stored as string; validate in the adapter. |
| `DateTimeFieldConfig` | `datetime` | `DateTimeInput` | Stored as string; validate in the adapter. |

### Type-Specific Parameters

| Class | Parameter | Type | Default | Description |
|-------|-----------|------|---------|-------------|
| `CharFieldConfig` | `max_length` | `int \| None` | `None` | Maximum length for `char` fields. |
| `ChoicesFieldConfig` | `choices` | `list[tuple[str, str]]` | `[]` | `(value, label)` pairs for `choices` fields. |
| `FKFieldConfig` | `model` | `str \| None` | `None` | `"app_label.ModelName"` for Django FK resolution. |
| `FKFieldConfig` | `to_field` | `str \| None` | `None` | Model field to use as the FK value. |
| `FKFieldConfig` | `display_field` | `str \| None` | `None` | Field to show when resolving FK labels. |
| `FKFieldConfig` | `service` | `str \| None` | `None` | Service name in the adapter registry for gRPC FK resolution. |
| `FKFieldConfig` | `get_method` | `str` | `"get"` | Adapter method to call for gRPC FK resolution. |

## Class Methods

### `get_field_configs()`

Returns the list of field config objects defined on the class.

```python
>>> Product.get_field_configs()
[CharFieldConfig(name='id', ...), CharFieldConfig(name='name', ...), ...]
```

### `get_field_names()`

Returns a list of field name strings.

```python
>>> Product.get_field_names()
['id', 'name', 'price', 'active']
```

### `get_field_config(name)`

Returns the field config for a given field name, or `None`.

```python
>>> Product.get_field_config("price")
FloatFieldConfig(name='price', type='float', label='Price')
```

### `from_response(response)`

Creates a resource instance from a gRPC response object or dictionary. Uses the `source` attribute on each field config to map response keys to field names.

```python
# Protobuf response
product = Product.from_response(grpc_response)

# Dictionary response
product = Product.from_response({
    "id": "123",
    "product_name": "Widget",  # source="product_name" on the field config
    "price": 9.99,
    "is_active": True,
})
```

Override this method when the response shape does not map 1-to-1 to field names.

```python
class Product(BaseGrpcResource):
    @classmethod
    def from_response(cls, response):
        return cls(
            id=response.product_id,
            name=response.product_name,
            price=response.product_price,
            active=response.is_active,
        )
```

### `admin_model()`

Creates and returns a fake Django model class. This class has `_meta`, `objects`, `DoesNotExist`, and `MultipleObjectsReturned` so that Django's `ModelAdmin` can work with it.

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    ...
```

### `build_form_class(widgets=None)`

Builds a Django `Form` subclass dynamically from the resource's field configs.

```python
form_class = Product.build_form_class(widgets={
    "description": forms.Textarea(attrs={"rows": 8}),
})
```

## Instance Properties

### `pk`

Returns the primary key value. The field used is determined by `Meta.pk_field` (default `"id"`).

```python
product = Product(id="123", name="Widget")
assert product.pk == "123"
```

### `__str__`

Returns `str(self.pk)` by default. Override if you want a different string representation.

## Examples

### Foreign Key to a Django Model

```python
from django_admin_grpc.resources import CharFieldConfig, FKFieldConfig

class Order(BaseGrpcResource):
    class Meta:
        app_label = "sales"
        pk_field = "order_id"

    fields = [
        CharFieldConfig(name="order_id"),
        FKFieldConfig(
            name="customer_id",
            label="Customer",
            model="auth.User",
            display_field="username",
            required=False,
        ),
    ]
```

### Foreign Key to Another gRPC Service

```python
from django_admin_grpc.resources import CharFieldConfig, FKFieldConfig

class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id"),
        CharFieldConfig(name="name"),
        FKFieldConfig(
            name="category_id",
            label="Category",
            service="catalog_category",
            get_method="get_category",
            display_field="name",
        ),
    ]
```

### Field with a Different Source Name

When the gRPC response uses different field names than your resource:

```python
from django_admin_grpc.resources import CharFieldConfig, FloatFieldConfig

class Product(BaseGrpcResource):
    fields = [
        CharFieldConfig(name="id"),
        CharFieldConfig(name="name", source="product_name"),
        FloatFieldConfig(name="price", source="unit_price"),
    ]
```

### Choices Field

```python
from django_admin_grpc.resources import CharFieldConfig, ChoicesFieldConfig

class Product(BaseGrpcResource):
    fields = [
        CharFieldConfig(name="id"),
        ChoicesFieldConfig(name="status", choices=[
            ("draft", "Draft"),
            ("published", "Published"),
            ("archived", "Archived"),
        ]),
    ]
```
