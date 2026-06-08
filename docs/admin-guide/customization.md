# Customization

## Custom Widgets

Override widgets per field when building the form class:

```python
from django import forms
from django_grpc_admin.admin import GrpcResourceAdmin

class ProductAdmin(GrpcResourceAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
    grpc_form_fields = ["name", "description", "price", "active"]

    def _build_form_class(self):
        return self.resource_class.build_form_class(
            widgets={
                "description": forms.Textarea(attrs={"rows": 8}),
                "price": forms.NumberInput(attrs={"step": "0.01"}),
            }
        )
```

Or set defaults globally in `settings.py`:

```python
GRPC_ADMIN = {
    "DEFAULT_WIDGETS": {
        "char": forms.TextInput,
        "text": forms.Textarea,
        "boolean": forms.CheckboxInput,
    },
}
```

## Custom Admin Base Class

`GrpcResourceAdmin` inherits from Django's `ModelAdmin`. If you use a custom admin theme (e.g. django-unfold, django-jazzmin), subclass with the theme's `ModelAdmin` **after** `GrpcResourceAdmin`:

```python
from django.contrib import admin
from django_grpc_admin.admin import GrpcResourceAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin

class MyGrpcAdmin(GrpcResourceAdmin, UnfoldModelAdmin):
    pass

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
```

Alternatively, use the factory helper:

```python
MyGrpcAdmin = GrpcResourceAdmin.with_base(UnfoldModelAdmin)

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
```

## Custom Templates

### Per-Resource Templates

Override templates via the resource `Meta` class:

```python
class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        change_form_template = "myapp/product_change_form.html"
        delete_confirm_template = "myapp/product_delete_confirm.html"
```

### Global Templates

Set defaults in `settings.py`:

```python
GRPC_ADMIN = {
    "DEFAULT_CHANGE_FORM_TEMPLATE": "myapp/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "myapp/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "myapp/cursor_pagination.html",
}
```

### Template Resolution Order

For change form templates, the admin looks in this order:

1. `grpc_add_form_template` attribute on the admin class (for add view only)
2. Resource `Meta.change_form_template`
3. `GRPC_ADMIN['DEFAULT_CHANGE_FORM_TEMPLATE']`
4. Package default: `django_grpc_admin/change_form.html`

For delete confirmation:

1. `grpc_delete_template` attribute on the admin class
2. Resource `Meta.delete_confirm_template`
3. `GRPC_ADMIN['DEFAULT_DELETE_CONFIRM_TEMPLATE']`
4. Package default: `django_grpc_admin/delete_confirm.html`

## Custom Detail Sections

Control which fields appear in the read-only detail section of the change view:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_detail_fields = ["id", "name", "description", "price", "active"]
```

With custom labels:

```python
class ProductAdmin(GrpcResourceAdmin):
    grpc_detail_fields = [
        ("Product ID", "id"),
        ("Product Name", "name"),
        ("Retail Price", "price"),
    ]
```

If `grpc_detail_fields` is not set, all resource fields are shown.

## Custom List Columns

Use `admin.display` decorators for computed columns:

```python
class ProductAdmin(GrpcResourceAdmin):
    list_display = ["id", "name", "formatted_price", "status_badge"]

    @admin.display(description="Price", ordering="price")
    def formatted_price(self, obj):
        return f"${obj.price:.2f}"

    @admin.display(description="Status")
    def status_badge(self, obj):
        if obj.active:
            return "✅ Active"
        return "❌ Inactive"
```

## Custom CSS / JS

Add custom media to the admin class:

```python
class ProductAdmin(GrpcResourceAdmin):
    class Media:
        css = {
            "all": ("myapp/css/admin.css",)
        }
        js = ("myapp/js/admin.js",)
```

## Custom URL Patterns

Add custom views to the admin:

```python
from django.urls import path
from django.http import JsonResponse

class ProductAdmin(GrpcResourceAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "export/",
                self.admin_site.admin_view(self.export_view),
                name="catalog_product_export",
            ),
        ]
        return custom_urls + urls

    def export_view(self, request):
        adapter = self.get_adapter()
        result = adapter.list(self.resource_class, page=1, page_size=1000)
        data = [{"id": obj.pk, "name": obj.name} for obj in result.items]
        return JsonResponse({"products": data})
```

## Custom Actions with Confirmation

Add actions that show an intermediate page:

```python
from django.contrib import messages
from django.template.response import TemplateResponse

class ProductAdmin(GrpcResourceAdmin):
    actions = ["bulk_update_status"]

    @admin.action(description="Update status for selected products")
    def bulk_update_status(self, request, queryset):
        if "apply" in request.POST:
            new_status = request.POST.get("new_status")
            adapter = self.get_adapter()
            for obj in queryset:
                adapter.update(self.resource_class, obj.pk, {"status": new_status})
            messages.success(request, f"Updated status to {new_status}")
            return

        return TemplateResponse(
            request,
            "myapp/bulk_update_status.html",
            context={
                "title": "Update Status",
                "products": queryset,
                "opts": self._fake_model._meta,
            },
        )
```
