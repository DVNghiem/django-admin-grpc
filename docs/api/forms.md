# API Reference — Forms

## `GrpcAdminForm`

Base form for gRPC-backed admin create/edit views. Inherits from `forms.Form`.

### Methods

#### `get_create_data() -> dict[str, Any]`

Return the payload to send to `adapter.create()`. Default returns `dict(self.cleaned_data)`.

Override to transform data:

```python
class ProductForm(GrpcAdminForm):
    def get_create_data(self):
        data = super().get_create_data()
        data["slug"] = slugify(data["name"])
        return data
```

#### `get_update_data() -> dict[str, Any]`

Return the payload to send to `adapter.update()`. Default returns `dict(self.cleaned_data)`.

## `FormBuilder`

Builds a Django `Form` class from a `BaseGrpcResource` definition.

### Class Attributes

#### `DEFAULT_WIDGETS: dict[str, str]`

Mapping of field type to dotted widget path.

```python
{
    "char": "django.forms.widgets.TextInput",
    "text": "django.forms.widgets.Textarea",
    "integer": "django.forms.widgets.NumberInput",
    "boolean": "django.forms.widgets.CheckboxInput",
    "choices": "django.forms.widgets.Select",
    "float": "django.forms.widgets.NumberInput",
    "fk": "django.forms.widgets.Select",
    "datetime": "django.forms.widgets.DateTimeInput",
    "date": "django.forms.widgets.DateInput",
}
```

### Methods

#### `build(resource_class, widgets=None, field_names=None) -> type[forms.Form]`

Build and return a `Form` subclass.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `resource_class` | `type[BaseGrpcResource]` | — | Resource whose fields drive form generation. |
| `widgets` | `dict \| None` | `None` | Mapping of field name to widget instance or dotted path. |
| `field_names` | `list[str] \| None` | `None` | Fields to include. If `None`, all fields are included. |

**Returns:** A `Form` subclass named `{ResourceClass}Form`.

```python
from django_admin_grpc.forms import FormBuilder

form_class = FormBuilder.build(
    Product,
    widgets={"description": forms.Textarea(attrs={"rows": 8})},
    field_names=["name", "price"],
)
```

#### `_make_form_field(config, widgets=None) -> forms.Field | None`

Create a single form field from a field config.

**Field type mapping:**

| Config Type | Form Field | Notes |
|-------------|-----------|-------|
| `char` | `CharField` | `max_length` defaults to 255. |
| `text` | `CharField` + `Textarea` | 4 rows by default. |
| `integer` | `IntegerField` | — |
| `float` | `FloatField` | — |
| `boolean` | `BooleanField` | Always `required=False`. |
| `choices` | `ChoiceField` | Prepends `"---"` option. |
| `fk` | `ModelPKChoiceField` or `ChoiceField` | Django model FK or select options from `choices` / `choices_loader`. |
| `date` / `datetime` | `CharField` | With date/datetime widget. |
| unknown | `CharField` | Logs a warning. |

#### `_resolve_widget(config, widgets=None)`

Resolve the widget for a field config.

Resolution order:

1. Name-based lookup in `widgets` dict
2. Type-based lookup in `widgets` dict
3. `None` (uses FormBuilder defaults)

#### `_make_fk_field(config, widget=None)`

Create a foreign key form field.

If `config.model` is set, creates a `ModelPKChoiceField` with the Django model's queryset.

If `config.model` is not set, falls back to a plain `CharField`.

## `ModelPKChoiceField`

A `ModelChoiceField` that returns the raw PK value instead of the model instance.

### Methods

#### `to_python(value) -> Any`

Look up the model instance and return its PK.

#### `prepare_value(value) -> Any`

Return the PK value for form rendering.

### Why use ModelPKChoiceField?

gRPC services typically expect raw ID values, not Django model instances. `ModelPKChoiceField` lets users select from a dropdown of Django model instances while the form returns just the ID string or integer.

```python
# In a form:
customer_id = ModelPKChoiceField(
    queryset=User.objects.all(),
    to_field_name="pk",
)

# cleaned_data["customer_id"] will be 42, not a User instance
```
