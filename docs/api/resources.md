# API Reference — Resources

## `BaseGrpcResource`

Declarative base class for gRPC-backed entities.

### Attributes

#### `fields: ClassVar[list[BaseFieldConfig]]`

List of field config objects describing every exposed column. Must be defined on subclasses.

### Methods

#### `__init__(**kwargs)`

Create an instance. Sets each field from `kwargs`.

```python
product = Product(id="123", name="Widget", price=9.99, active=True)
```

#### `pk` (property)

Return the primary-key value. Uses `Meta.pk_field` (default `"id"`).

```python
product.pk  # "123"
```

#### `get_field_configs() -> list[BaseFieldConfig]`

Return the list of field configurations.

```python
Product.get_field_configs()
```

#### `get_field_names() -> list[str]`

Return a list of field name strings.

```python
Product.get_field_names()  # ["id", "name", "price", "active"]
```

#### `get_field_config(name: str) -> BaseFieldConfig | None`

Return the field config for a field name, or `None`.

```python
Product.get_field_config("price")
```

#### `from_response(response: Any) -> BaseGrpcResource`

Create an instance from a gRPC response object or mapping.

```python
product = Product.from_response(grpc_response)
```

Override when the response shape does not map 1-to-1 to field names.

#### `admin_model() -> type`

Create a fake Django model class for admin compatibility.

```python
FakeModel = Product.admin_model()
# FakeModel has: _meta, objects, DoesNotExist, MultipleObjectsReturned
```

#### `build_form_class(widgets=None) -> type[forms.Form]`

Build a Django `Form` subclass dynamically from field configs.

```python
form_class = Product.build_form_class(widgets={
    "description": forms.Textarea(attrs={"rows": 8}),
})
```

## `BaseFieldConfig`

Base dataclass for all field configurations.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `str` | — | Field identifier. |
| `label` | `str \| None` | auto | Human label. |
| `required` | `bool` | `True` | Whether required in forms. |
| `help_text` | `str` | `""` | Help text. |
| `initial` | `Any` | `None` | Default value. |
| `source` | `str \| None` | `None` | Response attribute name. |

### Methods

#### `__post_init__()`

Auto-generates `label` from `name` if not provided (title-cased with spaces).

## Concrete Field Config Classes

All concrete classes inherit from `BaseFieldConfig` and add a read-only `type` property.

| Class | `type` | Type-specific attributes |
|-------|--------|--------------------------|
| `CharFieldConfig` | `char` | `max_length: int \| None = None` |
| `TextFieldConfig` | `text` | — |
| `IntegerFieldConfig` | `integer` | — |
| `FloatFieldConfig` | `float` | — |
| `BooleanFieldConfig` | `boolean` | — |
| `ChoicesFieldConfig` | `choices` | `choices: list[tuple[str, str]] = []` |
| `DateFieldConfig` | `date` | — |
| `DateTimeFieldConfig` | `datetime` | — |
| `FKFieldConfig` | `fk` | `model`, `to_field`, `display_field`, `service`, `get_method` |

## `FakeModelMeta`

Stand-in for Django's `Options` (`model._meta`).

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `app_label` | `str` | App label from resource Meta. |
| `model_name` | `str` | Model name from resource Meta. |
| `verbose_name` | `str` | Singular display name. |
| `verbose_name_plural` | `str` | Plural display name. |
| `object_name` | `str` | Resource class name. |
| `pk` | `Any` | Primary key field object. |
| `app_config` | `Any` | Fake or real app config. |

### Methods

#### `get_field(name: str) -> Any`

Return a field-like object or raise `FieldDoesNotExist`.

#### `get_fields() -> list`

Return empty list (no real fields).

## `GrpcFakeQuerySet`

Minimal QuerySet stand-in for admin actions.

### Methods

#### `all() -> GrpcFakeQuerySet`

Return self.

#### `filter(**kwargs) -> GrpcFakeQuerySet`

Support `pk__in` filtering for bulk actions.

#### `order_by(*args) -> GrpcFakeQuerySet`

Return self.

#### `none() -> GrpcFakeQuerySet`

Return empty queryset.

## `ModelWrapper`

Wraps a `BaseGrpcResource` instance for template compatibility.

### Methods

#### `__getattr__(name: str) -> Any`

Delegate to the wrapped instance.

#### `__setattr__(name: str, value: Any) -> None`

Delegate to the wrapped instance (except `_meta` and `_instance`).

#### `serializable_value(field_name: str) -> Any`

Return the field value for admin list rendering.
