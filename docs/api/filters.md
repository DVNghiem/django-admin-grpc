# API Reference — Filters

## `GrpcFieldListFilter`

Base filter that avoids any database access. Inherits from Django's `FieldListFilter` but bypasses the `__init__` that triggers ORM queries.

### Methods

#### `expected_parameters() -> list[str]`

Return the query-string parameter names this filter uses.

#### `choices(changelist)`

Return filter choices for rendering. Base implementation returns empty list.

## `GrpcBooleanFieldListFilter`

Filter for boolean fields — renders Yes / No / All dropdown.

### Parameters

Inherits all `GrpcFieldListFilter` parameters.

### Behavior

- Parameter: `{field_path}__exact`
- Values: `"1"` (Yes), `"0"` (No)
- Choices: All, Yes, No

## `GrpcChoicesFieldListFilter`

Filter for fields with a fixed set of choices.

### Parameters

Inherits all `GrpcFieldListFilter` parameters plus:

| Name | Type | Description |
|------|------|-------------|
| `choices` | `list[tuple[str, str]]` | `(value, label)` pairs. |

### Behavior

- Parameter: `{field_path}__exact`
- Choices: All, plus each provided choice

## `GrpcSimpleListFilter`

Base class for custom gRPC filters. Modelled on Django's `SimpleListFilter`.

### Class Attributes

#### `title: str`

Human-readable filter title.

#### `parameter_name: str`

Query-string parameter name.

### Methods

#### `lookups(request, model_admin) -> list[tuple[str, str]]`

Return `(value, display)` pairs for the filter dropdown.

```python
class StatusFilter(GrpcSimpleListFilter):
    title = "Status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [
            ("draft", "Draft"),
            ("published", "Published"),
        ]
```

#### `queryset(request, queryset)`

No-op — filtering is handled by `get_grpc_filters()`.

## `GrpcTextInputFilter`

A free-text filter that renders a text input.

### Parameters

Inherits from `FieldListFilter` but bypasses ORM `__init__`.

### Class Attributes

#### `template: str`

Template path. Left blank by default so Django admin falls back to its default rendering.

### Behavior

- Parameter: `{field_path}`
- Renders a text input for free-text filtering

## `create_grpc_filter_spec(field_name, field_type="text", choices=None)`

Factory function that returns a `FieldListFilter` subclass.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `field_name` | `str` | — | The query-string parameter / field name. |
| `field_type` | `str` | `"text"` | `"boolean"`, `"choices"`, or `"text"`. |
| `choices` | `list[tuple] \| None` | `None` | Required when `field_type="choices"`. |

### Returns

A `FieldListFilter` subclass ready for `list_filter`.

### Example

```python
from django_admin_grpc.filters import create_grpc_filter_spec

filter_class = create_grpc_filter_spec(
    "status",
    field_type="choices",
    choices=[("draft", "Draft"), ("published", "Published")],
)
```
