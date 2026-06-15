"""
Settings helpers for django-admin-grpc.
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
    "GRPC_ADMIN_POOL_MIN_SIZE": 2,
    "GRPC_ADMIN_POOL_MAX_SIZE": 10,
    "GRPC_ADMIN_POOL_MAX_IDLE_SECONDS": 300.0,
    "GRPC_ADMIN_POOL_HEALTH_CHECK_INTERVAL": 30.0,
    "GRPC_ADMIN_POOL_HEALTH_CHECK_TIMEOUT": 2.0,
    "DEFAULT_WIDGETS": None,
    "DEFAULT_ADMIN_CLASS": "django.contrib.admin.ModelAdmin",
    "DEFAULT_CHANGE_FORM_TEMPLATE": "django_admin_grpc/change_form.html",
    "DEFAULT_DELETE_CONFIRM_TEMPLATE": "django_admin_grpc/delete_confirm.html",
    "DEFAULT_CURSOR_PAGINATION_TEMPLATE": "django_admin_grpc/cursor_pagination.html",
}


def get_setting(name: str) -> Any:
    """Return a django-admin-grpc setting, falling back to the default.

    Resolution order:
    1. ``settings.GRPC_ADMIN[name]`` (nested dict — preferred)
    2. ``settings.<name>`` (flat attribute — backward compatibility)
    3. Built-in ``DEFAULTS``

    If the resolved value is a dotted Python path string and the setting
    key ends with ``_CLASS`` or ``_TEMPLATE``, it is imported automatically.
    """
    # 1. Try nested GRPC_ADMIN dict first (preferred)
    grpc_admin = getattr(settings, "GRPC_ADMIN", None)
    if grpc_admin is not None:
        if name in grpc_admin:
            value = grpc_admin[name]
        elif name.startswith("GRPC_ADMIN_") and name[11:] in grpc_admin:
            value = grpc_admin[name[11:]]
        else:
            value = getattr(settings, name, DEFAULTS.get(name))
    else:
        # 2. Fall back to flat setting attribute
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
