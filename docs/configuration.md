# Configuration

All django-grpc-admin settings live under a single `GRPC_ADMIN` dict in your Django `settings.py`.

```python
# settings.py
GRPC_ADMIN = {
    "GRPC_ADMIN_TRACE_CONTEXT_PROVIDER": "myapp.trace.get_trace_context",
    "GRPC_ADMIN_DEFAULT_PAGE_SIZE": 25,
    "GRPC_ADMIN_MAX_PAGE_SIZE": 100,
    "GRPC_ADMIN_CURSOR_PAGINATION": False,
    "GRPC_ADMIN_LOG_LEVEL": "INFO",
    "DEFAULT_WIDGETS": None,
    "DEFAULT_ADMIN_CLASS": "django.contrib.admin.ModelAdmin",
    "DEFAULT_CHANGE_FORM_TEMPLATE": "django_admin_grpc/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "django_admin_grpc/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "django_admin_grpc/cursor_pagination.html",
}
```

## Setting Reference

### GRPC_ADMIN_TRACE_CONTEXT_PROVIDER

A callable or dotted Python path that returns a dict of trace headers to inject into every gRPC call.

**Default:** `None`

**Example:**

```python
# myapp/trace.py
def get_trace_context():
    return {
        "x-request-id": get_current_request_id(),
        "x-trace-id": get_current_trace_id(),
    }

# settings.py
GRPC_ADMIN = {
    "GRPC_ADMIN_TRACE_CONTEXT_PROVIDER": "myapp.trace.get_trace_context",
}
```

The trace interceptor adds these as gRPC metadata on every outgoing call.

### GRPC_ADMIN_DEFAULT_PAGE_SIZE

Default number of items per page for list views.

**Default:** `25`

**Example:**

```python
GRPC_ADMIN = {
    "GRPC_ADMIN_DEFAULT_PAGE_SIZE": 50,
}
```

### GRPC_ADMIN_MAX_PAGE_SIZE

Maximum number of items per page. Currently advisory — the admin does not enforce this limit.

**Default:** `100`

### GRPC_ADMIN_CURSOR_PAGINATION

Enable cursor-based pagination globally. Individual resources can override this with `grpc_cursor_pagination` on the admin class.

**Default:** `False`

**Example:**

```python
GRPC_ADMIN = {
    "GRPC_ADMIN_CURSOR_PAGINATION": True,
}
```

### GRPC_ADMIN_LOG_LEVEL

Log level for the package logger.

**Default:** `"INFO"`

**Valid values:** `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`

### DEFAULT_WIDGETS

Dict mapping field type to widget class or dotted Python path. Overrides the built-in defaults for all resources.

**Default:** `None` (uses built-in defaults)

**Example:**

```python
GRPC_ADMIN = {
    "DEFAULT_WIDGETS": {
        "char": "django.forms.widgets.TextInput",
        "text": "django.forms.widgets.Textarea",
        "boolean": "django.forms.widgets.CheckboxInput",
        "date": "django.forms.widgets.DateInput",
        "datetime": "django.forms.widgets.DateTimeInput",
    },
}
```

### DEFAULT_ADMIN_CLASS

Dotted path to the base `ModelAdmin` subclass. Used when creating admin classes dynamically.

**Default:** `"django.contrib.admin.ModelAdmin"`

### DEFAULT_CHANGE_FORM_TEMPLATE

Template path for add/change views.

**Default:** `"django_admin_grpc/change_form.html"`

### DEFAULT_DELETE_CONFIRM_TEMPLATE

Template path for delete confirmation views.

**Default:** `"django_admin_grpc/delete_confirm.html"`

### DEFAULT_CURSOR_PAGINATION_TEMPLATE

Template path for cursor pagination controls.

**Default:** `"django_admin_grpc/cursor_pagination.html"`

## Per-Resource Overrides

Most settings can be overridden per resource via the admin class or resource `Meta`:

| Setting | Global | Per-Admin | Per-Resource |
|---------|--------|-----------|--------------|
| Page size | `GRPC_ADMIN_DEFAULT_PAGE_SIZE` | `list_per_page` | — |
| Cursor pagination | `GRPC_ADMIN_CURSOR_PAGINATION` | `grpc_cursor_pagination` | — |
| Change form template | `DEFAULT_CHANGE_FORM_TEMPLATE` | `grpc_add_form_template` | `Meta.change_form_template` |
| Delete confirm template | `DEFAULT_DELETE_CONFIRM_TEMPLATE` | `grpc_delete_template` | `Meta.delete_confirm_template` |
| Widgets | `DEFAULT_WIDGETS` | `_build_form_class()` | `build_form_class(widgets=...)` |

## Example: Complete Configuration

```python
# settings.py

GRPC_ADMIN = {
    "GRPC_ADMIN_TRACE_CONTEXT_PROVIDER": "myapp.middleware.get_request_headers",
    "GRPC_ADMIN_DEFAULT_PAGE_SIZE": 50,
    "GRPC_ADMIN_MAX_PAGE_SIZE": 200,
    "GRPC_ADMIN_CURSOR_PAGINATION": False,
    "GRPC_ADMIN_LOG_LEVEL": "INFO",
    "DEFAULT_WIDGETS": {
        "text": "django.forms.widgets.Textarea",
        "date": "django.forms.widgets.DateInput",
    },
    "DEFAULT_CHANGE_FORM_TEMPLATE": "myapp/admin/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "myapp/admin/delete_confirm.html",
}
```
