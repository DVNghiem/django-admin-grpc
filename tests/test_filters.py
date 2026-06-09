"""
Tests for django_admin_grpc.filters module.
"""
from unittest.mock import Mock

import pytest

from django_admin_grpc.filters import (
    GrpcBooleanFieldListFilter,
    GrpcChoicesFieldListFilter,
    GrpcDateRangeFilter,
    GrpcFieldListFilter,
    GrpcMultiChoicesFilter,
    GrpcNumberRangeFilter,
    GrpcSimpleListFilter,
    GrpcTextInputFilter,
    create_grpc_filter_spec,
)


@pytest.fixture
def fake_field():
    f = Mock()
    f.name = "status"
    f.verbose_name = "Status"
    return f


@pytest.fixture
def mock_request():
    req = Mock()
    req.GET = {}
    return req


@pytest.fixture
def mock_changelist():
    cl = Mock()
    cl.get_query_string.return_value = "?"
    return cl


class TestGrpcFieldListFilter:
    def test_init(self, fake_field, mock_request):
        f = GrpcFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "status"
        )
        assert f.field_path == "status"
        assert f.title == "Status"

    def test_init_fallback_title(self, mock_request):
        field = Mock()
        field.verbose_name = None
        f = GrpcFieldListFilter(
            field, mock_request, {}, Mock(), Mock(), "created_at"
        )
        assert f.title == "Created At"

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "status"
        )
        assert f.expected_parameters() == ["status", "status__exact"]

    def test_choices_empty(self, fake_field, mock_request, mock_changelist):
        f = GrpcFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "status"
        )
        assert list(f.choices(mock_changelist)) == []


class TestGrpcBooleanFieldListFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcBooleanFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "active"
        )
        assert f.lookup_kwarg == "active__exact"
        assert f.lookup_val is None

    def test_init_with_value(self, fake_field, mock_request):
        mock_request.GET = {"active__exact": "1"}
        f = GrpcBooleanFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "active"
        )
        assert f.lookup_val == "1"

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcBooleanFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "active"
        )
        assert f.expected_parameters() == ["active__exact"]

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcBooleanFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "active"
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[0]["display"] == "All"
        assert choices[0]["selected"] is True
        assert choices[1]["display"] == "Yes"
        assert choices[1]["selected"] is False
        assert choices[2]["display"] == "No"
        assert choices[2]["selected"] is False

    def test_choices_selected_yes(self, fake_field, mock_request, mock_changelist):
        mock_request.GET = {"active__exact": "1"}
        f = GrpcBooleanFieldListFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "active"
        )
        choices = list(f.choices(mock_changelist))
        assert choices[0]["selected"] is False
        assert choices[1]["selected"] is True
        assert choices[2]["selected"] is False


class TestGrpcChoicesFieldListFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcChoicesFieldListFilter(
            fake_field,
            mock_request,
            {},
            Mock(),
            Mock(),
            "status",
            choices=[("p", "Pending"), ("d", "Done")],
        )
        assert f.lookup_val is None
        assert f._choices == [("p", "Pending"), ("d", "Done")]

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcChoicesFieldListFilter(
            fake_field,
            mock_request,
            {},
            Mock(),
            Mock(),
            "status",
            choices=[("p", "Pending"), ("d", "Done")],
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[0]["display"] == "All"
        assert choices[1]["display"] == "Pending"
        assert choices[2]["display"] == "Done"

    def test_choices_selected(self, fake_field, mock_request, mock_changelist):
        mock_request.GET = {"status__exact": "p"}
        f = GrpcChoicesFieldListFilter(
            fake_field,
            mock_request,
            {},
            Mock(),
            Mock(),
            "status",
            choices=[("p", "Pending"), ("d", "Done")],
        )
        choices = list(f.choices(mock_changelist))
        assert choices[1]["selected"] is True


class TestGrpcSimpleListFilter:
    def test_queryset_no_op(self):
        f = GrpcSimpleListFilter(Mock(), {}, Mock(), Mock())
        qs = Mock()
        assert f.queryset(Mock(), qs) is qs


class TestGrpcTextInputFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcTextInputFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "name"
        )
        assert f.lookup_kwarg == "name"
        assert f.lookup_val == ""
        assert f.title == "Status"  # from fake_field.verbose_name

    def test_init_with_value(self, fake_field):
        f = GrpcTextInputFilter(
            fake_field, Mock(), {"name": "widget"}, Mock(), Mock(), "name"
        )
        assert f.lookup_val == "widget"

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcTextInputFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "name"
        )
        assert f.expected_parameters() == ["name"]

    def test_has_output(self, fake_field, mock_request):
        f = GrpcTextInputFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "name"
        )
        assert f.has_output() is True

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcTextInputFilter(
            fake_field, mock_request, {"name": "abc"}, Mock(), Mock(), "name"
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 1
        assert choices[0]["name"] == "name"
        assert choices[0]["value"] == "abc"


class TestGrpcNumberRangeFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcNumberRangeFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "price"
        )
        assert f.lookup_val_gte == ""
        assert f.lookup_val_lte == ""

    def test_init_with_values(self, fake_field, mock_request):
        f = GrpcNumberRangeFilter(
            fake_field,
            mock_request,
            {"price__gte": "10", "price__lte": "100"},
            Mock(),
            Mock(),
            "price",
        )
        assert f.lookup_val_gte == "10"
        assert f.lookup_val_lte == "100"

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcNumberRangeFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "price"
        )
        assert f.expected_parameters() == ["price__gte", "price__lte"]

    def test_has_output(self, fake_field, mock_request):
        f = GrpcNumberRangeFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "price"
        )
        assert f.has_output() is True

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcNumberRangeFilter(
            fake_field,
            mock_request,
            {"price__gte": "10", "price__lte": "100"},
            Mock(),
            Mock(),
            "price",
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 2
        assert choices[0]["name"] == "price__gte"
        assert choices[0]["value"] == "10"
        assert choices[1]["name"] == "price__lte"
        assert choices[1]["value"] == "100"


class TestGrpcDateRangeFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcDateRangeFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "created_at"
        )
        assert f.lookup_val_gte == ""
        assert f.lookup_val_lte == ""

    def test_init_with_values(self, fake_field, mock_request):
        f = GrpcDateRangeFilter(
            fake_field,
            mock_request,
            {"created_at__gte": "2024-01-01", "created_at__lte": "2024-12-31"},
            Mock(),
            Mock(),
            "created_at",
        )
        assert f.lookup_val_gte == "2024-01-01"
        assert f.lookup_val_lte == "2024-12-31"

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcDateRangeFilter(
            fake_field, mock_request, {}, Mock(), Mock(), "created_at"
        )
        assert f.expected_parameters() == ["created_at__gte", "created_at__lte"]

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcDateRangeFilter(
            fake_field,
            mock_request,
            {"created_at__gte": "2024-01-01", "created_at__lte": "2024-12-31"},
            Mock(),
            Mock(),
            "created_at",
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 2
        assert choices[0]["name"] == "created_at__gte"
        assert choices[1]["name"] == "created_at__lte"


class TestGrpcMultiChoicesFilter:
    def test_init_no_value(self, fake_field, mock_request):
        f = GrpcMultiChoicesFilter(
            fake_field,
            mock_request,
            {},
            Mock(),
            Mock(),
            "status",
            choices=[("active", "Active"), ("pending", "Pending")],
        )
        assert f.lookup_vals == []

    def test_init_with_comma_values(self, fake_field, mock_request):
        f = GrpcMultiChoicesFilter(
            fake_field,
            mock_request,
            {"status": "active,pending"},
            Mock(),
            Mock(),
            "status",
            choices=[("active", "Active"), ("pending", "Pending")],
        )
        assert f.lookup_vals == ["active", "pending"]

    def test_expected_parameters(self, fake_field, mock_request):
        f = GrpcMultiChoicesFilter(
            fake_field,
            mock_request,
            {},
            Mock(),
            Mock(),
            "status",
            choices=[("active", "Active")],
        )
        assert f.expected_parameters() == ["status", "status__in"]

    def test_choices(self, fake_field, mock_request, mock_changelist):
        f = GrpcMultiChoicesFilter(
            fake_field,
            mock_request,
            {"status": "active"},
            Mock(),
            Mock(),
            "status",
            choices=[("active", "Active"), ("pending", "Pending")],
        )
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[0]["display"] == "All"
        assert choices[1]["display"] == "Active"
        assert choices[1]["selected"] is True
        assert choices[2]["display"] == "Pending"
        assert choices[2]["selected"] is False

    def test_choices_multiple_selected(self, fake_field, mock_request, mock_changelist):
        f = GrpcMultiChoicesFilter(
            fake_field,
            mock_request,
            {"status": "active,pending"},
            Mock(),
            Mock(),
            "status",
            choices=[("active", "Active"), ("pending", "Pending")],
        )
        choices = list(f.choices(mock_changelist))
        assert choices[1]["selected"] is True
        assert choices[2]["selected"] is True


class TestCreateGrpcFilterSpec:
    def test_number_range_filter(self, mock_changelist):
        filter_class = create_grpc_filter_spec("price", "number_range")
        field = Mock()
        field.name = "price"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "price")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 2
        assert choices[0]["name"] == "price__gte"
        assert choices[1]["name"] == "price__lte"

    def test_date_range_filter(self, mock_changelist):
        filter_class = create_grpc_filter_spec("created_at", "date_range")
        field = Mock()
        field.name = "created_at"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "created_at")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 2
        assert choices[0]["name"] == "created_at__gte"
        assert choices[1]["name"] == "created_at__lte"

    def test_multi_choices_filter(self, mock_changelist):
        filter_class = create_grpc_filter_spec(
            "status", "multi_choices", [("active", "Active"), ("pending", "Pending")]
        )
        field = Mock()
        field.name = "status"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "status")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[1]["display"] == "Active"
        assert choices[2]["display"] == "Pending"

    def test_boolean_filter(self, mock_changelist):
        filter_class = create_grpc_filter_spec("active", "boolean")
        field = Mock()
        field.name = "active"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "active")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[1]["display"] == "Yes"
        assert choices[2]["display"] == "No"

    def test_choices_filter(self, mock_changelist):
        filter_class = create_grpc_filter_spec(
            "status", "choices", [("p", "Pending"), ("d", "Done")]
        )
        field = Mock()
        field.name = "status"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "status")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 3
        assert choices[1]["display"] == "Pending"

    def test_unknown_filter_type(self, mock_changelist):
        filter_class = create_grpc_filter_spec("name", "unknown")
        field = Mock()
        field.name = "name"
        f = filter_class(field, Mock(), {}, Mock(), Mock(), "name")
        choices = list(f.choices(mock_changelist))
        assert len(choices) == 1  # Only "All"

    def test_empty_value_display(self):
        mock_admin = Mock()
        mock_admin.get_empty_value_display.return_value = "N/A"
        filter_class = create_grpc_filter_spec("field", "text")
        field = Mock()
        f = filter_class(field, Mock(), {}, Mock(), mock_admin, "field")
        assert f.empty_value_display == "N/A"

    def test_selected_choice(self, mock_changelist):
        filter_class = create_grpc_filter_spec("active", "boolean")
        field = Mock()
        f = filter_class(field, Mock(), {"active__exact": "1"}, Mock(), Mock(), "active")
        choices = list(f.choices(mock_changelist))
        assert choices[1]["selected"] is True
