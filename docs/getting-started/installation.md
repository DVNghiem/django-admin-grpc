# Installation

## Requirements

- Python 3.10 or later
- Django 4.2 or later
- grpcio 1.50.0 or later

## Install from PyPI

```bash
pip install django-grpc-admin
```

## Install with development dependencies

If you plan to contribute or run the test suite:

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode along with:

| Package | Purpose |
|---------|---------|
| pytest | Test runner |
| pytest-django | Django test integration |
| pytest-cov | Coverage reporting |
| mypy | Static type checking |
| ruff | Linting and formatting |
| mkdocs | Documentation site generator |
| mkdocs-material | Documentation theme |

## Add to Django

Add `django_grpc_admin` to `INSTALLED_APPS` in your project's `settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_grpc_admin",  # <-- add this
    # your apps ...
]
```

!!! note "Order matters"
    Place `django_grpc_admin` after Django's built-in apps so its templates and static files can be overridden by your project if needed.

## Verify the installation

Start a Django shell and import the package:

```bash
python manage.py shell
```

```python
>>> import django_grpc_admin
>>> django_grpc_admin.__version__
'0.1.0'
```

If the import succeeds, the package is installed correctly.

## Optional: install a custom admin theme

django-grpc-admin works with popular Django admin themes such as [django-unfold](https://github.com/unfoldadmin/django-unfold) and [django-jazzmin](https://github.com/farridav/django-jazzmin). Install the theme as usual, then use `GrpcResourceAdmin.with_base()` to combine it with the gRPC admin base class.

```python
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from django_grpc_admin.admin import GrpcResourceAdmin

MyGrpcAdmin = GrpcResourceAdmin.with_base(UnfoldModelAdmin)

@admin.register(Product.admin_model())
class ProductAdmin(MyGrpcAdmin):
    resource_class = Product
    adapter_class = CatalogAdapter
```

See [Customization](../admin-guide/customization.md) for more details.
