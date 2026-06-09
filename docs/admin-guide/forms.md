# Forms

Forms in django-admin-grpc are built automatically from field config definitions. You can customize widgets, override the entire form, or transform data before it reaches the adapter.

## Automatic Form Building

By default, the admin builds a form from `grpc_form_fields` and the resource's field config list:

```python
@admin.register(Product.admin_model())
class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
    grpc_form_fields = ["name", "description", "price", "active"]
```

Only fields listed in `grpc_form_fields` appear in the add/change form. Fields not in this list are hidden from the form but can still appear in `list_display`.

## Custom Widgets Per Field

Override widgets when building the form class:

```python
from django import forms

class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
    grpc_form_fields = ["name", "description", "price", "active"]

    def _build_form_class(self):
        return self.resource_class.build_form_class(widgets={
            "description": forms.Textarea(attrs={"rows": 8}),
            "price": forms.NumberInput(attrs={"step": "0.01"}),
        })
```

Widget resolution order:

1. Name-based lookup in the `widgets` dict (e.g. `{"description": ...}`)
2. Type-based lookup in the `widgets` dict (e.g. `{"text": ...}`)
3. Package default widgets from `widgets.py`
4. Built-in defaults in `FormBuilder.DEFAULT_WIDGETS`

### Widgets Supported by Field Type

| Field Type | Default Widget | Common Overrides |
|------------|---------------|------------------|
| `char` | `TextInput` | `Textarea`, `URLInput`, `EmailInput` |
| `text` | `Textarea` | `Textarea(attrs={"rows": 10})` |
| `integer` | `NumberInput` | — |
| `float` | `NumberInput` | `NumberInput(attrs={"step": "0.01"})` |
| `boolean` | `CheckboxInput` | — |
| `choices` | `Select` | `RadioSelect`, `CheckboxSelectMultiple` |
| `fk` | `Select` | — |
| `date` | `DateInput` | `DateInput(attrs={"type": "date"})` |
| `datetime` | `DateTimeInput` | `DateTimeInput(attrs={"type": "datetime-local"})` |

## Global Default Widgets

Set default widgets for all resources in `settings.py`:

```python
GRPC_ADMIN = {
    "DEFAULT_WIDGETS": {
        "char": "django.forms.widgets.TextInput",
        "text": "django.forms.widgets.Textarea",
        "boolean": "django.forms.widgets.CheckboxInput",
    },
}
```

Values can be widget classes or dotted Python paths.

## Using build_form_class() on the Resource

You can also build forms directly from the resource class:

```python
from django import forms

form_class = Product.build_form_class(widgets={
    "name": forms.TextInput(attrs={"class": "vTextField"}),
})
```

## Custom Form Classes

For full control, create a custom form class and return it from `_build_form_class()`:

```python
from django import forms
from django_admin_grpc.forms import GrpcAdminForm

class ProductForm(GrpcAdminForm):
    name = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea, required=False)
    price = forms.DecimalField(max_digits=10, decimal_places=2)
    active = forms.BooleanField(required=False)

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return price

class ProductAdmin(GrpcResourceAdmin):
    def _build_form_class(self):
        return ProductForm
```

!!! note "Inherit from GrpcAdminForm"
    `GrpcAdminForm` provides `get_create_data()` and `get_update_data()` methods that the admin calls to extract the payload for the adapter. If you use a plain `forms.Form`, you must ensure `cleaned_data` contains the fields the adapter expects.

## Transforming Data Before Sending to gRPC

Override `get_grpc_create_data` and `get_grpc_update_data` on the admin class to transform `cleaned_data` before it reaches the adapter:

```python
class ProductAdmin(GrpcResourceAdmin):
    def get_grpc_create_data(self, cleaned_data):
        data = dict(cleaned_data)
        data["created_by"] = self.request.user.username
        data["created_at"] = timezone.now().isoformat()
        return data

    def get_grpc_update_data(self, obj, cleaned_data):
        data = dict(cleaned_data)
        data["updated_by"] = self.request.user.username
        data["updated_at"] = timezone.now().isoformat()
        return data
```

## Form Initial Data

Override `get_grpc_form_initial` to set default values when opening the change form:

```python
class ProductAdmin(GrpcResourceAdmin):
    def get_grpc_form_initial(self, obj):
        initial = super().get_grpc_form_initial(obj)
        initial["tags"] = ", ".join(obj.tags or [])
        return initial
```

## Read-Only Fields

To make fields read-only in the change view, do not include them in `grpc_form_fields`. They will still appear in the detail section below the form (if `grpc_detail_fields` is configured).

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_form_fields = ["name", "price"]  # description is read-only
    grpc_detail_fields = ["id", "name", "description", "price", "active"]
```

## Field Types and Validation

### CharField

```python
CharFieldConfig(name="name", max_length=200)
```

Generates a `forms.CharField` with `max_length` validation.

### TextField

```python
TextFieldConfig(name="description", required=False)
```

Generates a `forms.CharField` with a `Textarea` widget (4 rows by default).

### IntegerField

```python
IntegerFieldConfig(name="quantity")
```

Generates a `forms.IntegerField`.

### FloatField

```python
FloatFieldConfig(name="price")
```

Generates a `forms.FloatField`.

### BooleanField

```python
BooleanFieldConfig(name="active", initial=True)
```

Generates a `forms.BooleanField` (always `required=False`).

### ChoiceField

```python
ChoicesFieldConfig(
    name="status",
    choices=[("draft", "Draft"), ("published", "Published")],
)
```

Generates a `forms.ChoiceField` with a `Select` widget.

### Foreign Key Field

```python
from django_admin_grpc.resources import FKFieldConfig

# Django model FK
FKFieldConfig(
    name="customer_id",
    model="auth.User",
    display_field="username",
)

# gRPC service FK
def load_categories():
    return [("1", "Hardware"), ("2", "Software")]

FKFieldConfig(
    name="category_id",
    service="catalog_category",
    get_method="get_category",
    display_field="name",
    choices_loader=load_categories,
)
```

Generates a select field for every FK. Django model FKs are populated automatically from the database. Service-backed FKs should provide `choices` or `choices_loader`; without them the field still renders as a select, but only contains the empty option.

!!! info "ModelPKChoiceField"
    `ModelPKChoiceField` is a custom `ModelChoiceField` that returns the raw primary key value instead of the model instance. This is what gRPC services typically expect.

!!! info "Display fields"
    Set `display_field="name"` to show a related object's `name` in detail views. If `display_field` is omitted, django-admin-grpc shows the raw FK value.

### Date / DateTime Fields

```python
from django_admin_grpc.resources import DateFieldConfig, DateTimeFieldConfig

DateTimeFieldConfig(name="created_at")
DateFieldConfig(name="birth_date")
```

Generates a `forms.CharField` with a `DateTimeInput` or `DateInput` widget. The actual date parsing/validation should happen in your adapter.
