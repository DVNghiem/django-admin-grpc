"""
Tests for django_admin_grpc.settings module.
"""
from unittest.mock import patch

import pytest

from django_admin_grpc.settings import get_setting


class TestGetSetting:
    def test_returns_default_when_not_overridden(self):
        assert get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE") == 25

    def test_returns_django_setting_when_overridden(self):
        with patch(
            "django_admin_grpc.settings.settings",
            GRPC_ADMIN_DEFAULT_PAGE_SIZE=50,
        ):
            assert get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE") == 50

    def test_imports_class_setting(self):
        with patch(
            "django_admin_grpc.settings.settings",
            DEFAULT_ADMIN_CLASS="django.contrib.admin.ModelAdmin",
        ):
            result = get_setting("DEFAULT_ADMIN_CLASS")
            assert result.__name__ == "ModelAdmin"

    def test_imports_class_setting_failure_raises(self):
        with patch(
            "django_admin_grpc.settings.settings",
            DEFAULT_ADMIN_CLASS="nonexistent.module.Class",
        ), pytest.raises(ImportError):
            get_setting("DEFAULT_ADMIN_CLASS")

    def test_returns_template_path_as_string(self):
        with patch(
            "django_admin_grpc.settings.settings",
            DEFAULT_CHANGE_FORM_TEMPLATE="myapp/change_form.html",
        ):
            result = get_setting("DEFAULT_CHANGE_FORM_TEMPLATE")
            assert result == "myapp/change_form.html"

    def test_returns_none_for_none_default(self):
        assert get_setting("DEFAULT_WIDGETS") is None

    def test_reads_from_grpc_admin_nested_dict(self):
        """Regression: get_setting must read from settings.GRPC_ADMIN['NAME']."""
        with patch(
            "django_admin_grpc.settings.settings",
            GRPC_ADMIN={"DEFAULT_WIDGETS": {"name": "TextInput"}},
        ):
            result = get_setting("DEFAULT_WIDGETS")
            assert result == {"name": "TextInput"}

    def test_grpc_admin_nested_dict_takes_precedence_over_flat_setting(self):
        """Nested GRPC_ADMIN dict should take precedence over flat settings attr."""
        with patch(
            "django_admin_grpc.settings.settings",
            GRPC_ADMIN={"DEFAULT_PAGE_SIZE": 100},
            GRPC_ADMIN_DEFAULT_PAGE_SIZE=50,  # flat setting — should be ignored
        ):
            result = get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE")
            assert result == 100

    def test_fallback_to_flat_setting_when_not_in_grpc_admin(self):
        """If key not in GRPC_ADMIN dict, fall back to flat settings attr."""
        with patch(
            "django_admin_grpc.settings.settings",
            GRPC_ADMIN={"DEFAULT_WIDGETS": {"name": "TextInput"}},
            GRPC_ADMIN_DEFAULT_PAGE_SIZE=75,
        ):
            result = get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE")
            assert result == 75
