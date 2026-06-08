# Contributing

Thank you for your interest in improving django-grpc-admin! This page covers how to set up your environment, run tests, and submit changes.

## Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/DVNghiem/django-admin-grpc.git
   cd django-grpc-admin
   ```

2. **Create a virtual environment:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install in editable mode with dev dependencies:**

   ```bash
   pip install -e ".[dev]"
   ```

4. **Verify the setup:**

   ```bash
   pytest
   ```

   All tests should pass with 80%+ coverage.

## Project Structure

```
django-grpc-admin/
├── src/django_admin_grpc/     # Package source code
│   ├── __init__.py
│   ├── admin.py                # GrpcResourceAdmin, GrpcChangeList
│   ├── adapters.py             # BaseGrpcServiceAdapter
│   ├── exceptions.py           # Exception hierarchy
│   ├── filters.py              # List filters
│   ├── forms.py                # FormBuilder, ModelPKChoiceField
│   ├── interceptors.py         # TraceClientInterceptor
│   ├── mappers.py              # BaseGrpcMapper, DefaultGrpcMapper
│   ├── models.py               # FakeModelMeta, GrpcFakeQuerySet, ModelWrapper
│   ├── paginator.py            # PagedResult, GrpcPaginator
│   ├── registry.py             # AdapterRegistry
│       ├── resources.py            # BaseGrpcResource, field config classes
│   ├── settings.py             # Settings helpers
│   ├── widgets.py              # Default widget mappings
│   └── templates/              # Admin templates
├── tests/                       # Test suite
├── example/                     # Example Django project
├── docs/                        # MkDocs documentation
├── README.md
├── pyproject.toml
└── mkdocs.yml
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=django_admin_grpc --cov-report=term-missing

# Run a specific test file
pytest tests/test_resources.py

# Run a specific test
pytest tests/test_resources.py::TestBaseGrpcResource::test_from_response
```

Coverage must remain at 80% or higher.

## Code Style

We use **ruff** for linting and formatting, and **mypy** for type checking.

```bash
# Lint and format
ruff check src tests
ruff format src tests

# Type check
mypy src/django_admin_grpc
```

Configuration is in `pyproject.toml`:

- Line length: 100 characters
- Target Python version: 3.10+
- Enforced rules: E, F, W, I, N, UP, B, C4, SIM

## Writing Tests

- Place tests in `tests/`
- Name test files `test_<module>.py`
- Use pytest fixtures for setup
- Mock gRPC calls — do not require a running gRPC server
- Cover both success and error paths

### Example Test

```python
import pytest
from django_admin_grpc.resources import BaseGrpcResource, CharFieldConfig

class Product(BaseGrpcResource):
    class Meta:
        app_label = "catalog"
        pk_field = "id"

    fields = [
        CharFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]

def test_from_response_dict():
    product = Product.from_response({"id": "123", "name": "Widget"})
    assert product.id == "123"
    assert product.name == "Widget"

def test_admin_model_has_meta():
    model = Product.admin_model()
    assert model._meta.app_label == "catalog"
    assert model._meta.model_name == "product"
```

## Submitting Changes

1. **Create a branch:**

   ```bash
   git checkout -b feature/my-change
   ```

2. **Make your changes** with tests.

3. **Ensure tests pass:**

   ```bash
   pytest
   ruff check src tests
   mypy src/django_admin_grpc
   ```

4. **Commit with a clear message:**

   ```bash
   git commit -m "feat(filters): add text input filter for free-text search"
   ```

5. **Open a pull request** with:
   - A clear description of the change
   - Motivation (what problem it solves)
   - Test coverage for new functionality

## Documentation

If your change affects user-facing behavior, update the relevant documentation in `docs/`.

Preview documentation locally:

```bash
mkdocs serve
```

Then visit `http://127.0.0.1:8000`.

## Reporting Issues

When reporting bugs, please include:

- Python and Django versions
- A minimal reproduction case
- Expected vs actual behavior
- Any relevant error messages or stack traces

## Code of Conduct

Be respectful, constructive, and inclusive. We welcome contributors of all experience levels.
