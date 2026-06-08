"""
Tests for django_grpc_admin.settings module.
"""
from unittest.mock import patch

import pytest

from django_grpc_admin.settings import get_setting


class TestGetSetting:
    def test_returns_default_when_not_overridden(self):
        assert get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE") == 25

    def test_returns_django_setting_when_overridden(self):
        with patch(
            "django_grpc_admin.settings.settings",
            GRPC_ADMIN_DEFAULT_PAGE_SIZE=50,
        ):
            assert get_setting("GRPC_ADMIN_DEFAULT_PAGE_SIZE") == 50

    def test_imports_class_setting(self):
        with patch(
            "django_grpc_admin.settings.settings",
            DEFAULT_ADMIN_CLASS="django.contrib.admin.ModelAdmin",
        ):
            result = get_setting("DEFAULT_ADMIN_CLASS")
            assert result.__name__ == "ModelAdmin"

    def test_imports_class_setting_failure_raises(self):
        with patch(
            "django_grpc_admin.settings.settings",
            DEFAULT_ADMIN_CLASS="nonexistent.module.Class",
        ), pytest.raises(ImportError):
            get_setting("DEFAULT_ADMIN_CLASS")

    def test_returns_template_path_as_string(self):
        with patch(
            "django_grpc_admin.settings.settings",
            DEFAULT_CHANGE_FORM_TEMPLATE="myapp/change_form.html",
        ):
            result = get_setting("DEFAULT_CHANGE_FORM_TEMPLATE")
            assert result == "myapp/change_form.html"

    def test_returns_none_for_none_default(self):
        assert get_setting("DEFAULT_WIDGETS") is None
