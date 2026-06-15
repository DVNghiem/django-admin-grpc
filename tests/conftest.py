"""
Pytest fixtures and configuration for django-admin-grpc tests.
"""
import django
import pytest
from django.conf import settings


@pytest.fixture(scope="session", autouse=True)
def django_settings():
    """
    Ensure Django is configured for the test session.
    This is a no-op because pytest-django picks up DJANGO_SETTINGS_MODULE,
    but we keep it for explicit documentation.
    """
    if not settings.configured:
        settings.configure(
            SECRET_KEY="test-secret-key",
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "django.contrib.admin",
                "django.contrib.messages",
                "django_admin_grpc",
            ],
            USE_TZ=True,
        )
        django.setup()
    yield settings


@pytest.fixture
def reset_registry():
    """Reset the adapter registry before/after each test."""
    from django_admin_grpc.registry import adapter_registry

    adapter_registry.clear()
    yield adapter_registry
    adapter_registry.clear()


@pytest.fixture
def reset_async_registry():
    """Reset the async adapter registry before/after each test."""
    from django_admin_grpc.async_adapter import async_adapter_registry

    async_adapter_registry.clear()
    yield async_adapter_registry
    async_adapter_registry.clear()
