"""
Settings helpers for django-grpc-admin.
"""
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

DEFAULTS: dict[str, Any] = {
    "GRPC_ADMIN_TRACE_CONTEXT_PROVIDER": None,
    "GRPC_ADMIN_DEFAULT_PAGE_SIZE": 25,
    "GRPC_ADMIN_MAX_PAGE_SIZE": 100,
    "GRPC_ADMIN_CURSOR_PAGINATION": False,
    "GRPC_ADMIN_LOG_LEVEL": "INFO",
    "DEFAULT_WIDGETS": None,
    "DEFAULT_ADMIN_CLASS": "django.contrib.admin.ModelAdmin",
    "DEFAULT_CHANGE_FORM_TEMPLATE": "django_grpc_admin/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "django_grpc_admin/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "django_grpc_admin/cursor_pagination.html",
}


def get_setting(name: str) -> Any:
    """Return a django-grpc-admin setting, falling back to the default.

    If the resolved value is a dotted Python path string and the setting
    key ends with ``_CLASS`` or ``_TEMPLATE``, it is imported automatically.
    """
    value = getattr(settings, name, DEFAULTS.get(name))
    if value is None:
        return None
    if isinstance(value, str) and (name.endswith("_CLASS") or name.endswith("_TEMPLATE")):
        try:
            return import_string(value)
        except ImportError:
            # If it's not a valid dotted path, return the raw string
            # (this allows template paths to remain as strings).
            if name.endswith("_CLASS"):
                raise
            return value
    return value
