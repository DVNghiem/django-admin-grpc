"""
Tests for django_admin_grpc.forms module.
"""
from unittest.mock import Mock, patch

import pytest
from django import forms

from django_admin_grpc.forms import FormBuilder, GrpcAdminForm, ModelPKChoiceField
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    ChoicesFieldConfig,
    DateFieldConfig,
    DateTimeFieldConfig,
    FKFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
    TextFieldConfig,
)


class TestResource(BaseGrpcResource):
    class Meta:
        app_label = "test"
        model_name = "testresource"

    fields = [
        CharFieldConfig(name="name", label="Name", required=True),
        TextFieldConfig(name="description", label="Description"),
        IntegerFieldConfig(name="count", label="Count", initial=0),
        BooleanFieldConfig(name="active", label="Active"),
        ChoicesFieldConfig(
            name="status", label="Status", choices=[("a", "Active"), ("i", "Inactive")]
        ),
        FloatFieldConfig(name="rating", label="Rating"),
        FKFieldConfig(name="category", label="Category", model="auth.User"),
    ]


class TestGrpcAdminForm:
    def test_get_create_data(self):
        class MyForm(GrpcAdminForm):
            name = forms.CharField()

        form = MyForm(data={"name": "Widget"})
        form.is_valid()
        assert form.get_create_data() == {"name": "Widget"}

    def test_get_update_data(self):
        class MyForm(GrpcAdminForm):
            name = forms.CharField()

        form = MyForm(data={"name": "Updated"})
        form.is_valid()
        assert form.get_update_data() == {"name": "Updated"}


class TestFormBuilderBuild:
    def test_char_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["name"]
        assert isinstance(field, forms.CharField)
        assert field.label == "Name"
        assert field.required is True
        assert field.max_length == 255

    def test_text_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["description"]
        assert isinstance(field, forms.CharField)
        assert isinstance(field.widget, forms.Textarea)
        assert field.widget.attrs["rows"] == 4

    def test_integer_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["count"]
        assert isinstance(field, forms.IntegerField)
        assert field.initial == 0

    def test_boolean_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["active"]
        assert isinstance(field, forms.BooleanField)
        assert field.required is False

    def test_choices_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["status"]
        assert isinstance(field, forms.ChoiceField)
        assert field.choices == [("", "---"), ("a", "Active"), ("i", "Inactive")]

    def test_float_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["rating"]
        assert isinstance(field, forms.FloatField)

    def test_fk_field(self):
        form_class = FormBuilder.build(TestResource)
        field = form_class.base_fields["category"]
        assert isinstance(field, ModelPKChoiceField)
        assert field.required is True

    def test_custom_widget(self):
        form_class = FormBuilder.build(
            TestResource, widgets={"name": forms.Textarea()}
        )
        assert isinstance(form_class.base_fields["name"].widget, forms.Textarea)

    def test_custom_widget_string_path(self):
        form_class = FormBuilder.build(
            TestResource, widgets={"name": "django.forms.widgets.Textarea"}
        )
        assert isinstance(form_class.base_fields["name"].widget, forms.Textarea)

    def test_unknown_field_type_fallback(self):
        class UnknownResource(BaseGrpcResource):
            class Meta:
                app_label = "test"
                model_name = "unknown"

            fields = [CharFieldConfig(name="data")]

        form_class = FormBuilder.build(UnknownResource)
        field = form_class.base_fields["data"]
        assert isinstance(field, forms.CharField)

    def test_datetime_field(self):
        class DtResource(BaseGrpcResource):
            class Meta:
                app_label = "test"
                model_name = "dt"

            fields = [DateTimeFieldConfig(name="created")]

        form_class = FormBuilder.build(DtResource)
        assert isinstance(form_class.base_fields["created"], forms.CharField)

    def test_date_field(self):
        class DResource(BaseGrpcResource):
            class Meta:
                app_label = "test"
                model_name = "d"

            fields = [DateFieldConfig(name="birth")]

        form_class = FormBuilder.build(DResource)
        assert isinstance(form_class.base_fields["birth"], forms.CharField)


class TestFormBuilderDefaultWidgets:
    def test_uses_default_widgets_from_settings(self):
        from django import forms

        custom_widgets = {
            "char": forms.Textarea,
            "text": forms.TextInput,
        }

        with patch(
            "django_admin_grpc.widgets.get_default_widgets",
            return_value=custom_widgets,
        ):
            form_class = FormBuilder.build(TestResource)
            assert isinstance(form_class.base_fields["name"].widget, forms.Textarea)

    def test_uses_default_widgets_when_none_passed(self):
        form_class = FormBuilder.build(TestResource, widgets=None)
        # Should fall back to module-level DEFAULT_WIDGETS
        assert isinstance(form_class.base_fields["name"].widget, forms.TextInput)


class TestModelPKChoiceField:
    def test_to_python_with_int_pk(self):
        mock_model = Mock()
        mock_obj = Mock()
        mock_obj.pk = 42
        mock_qs = Mock()
        mock_qs.get.return_value = mock_obj
        mock_qs.model = mock_model
        mock_qs.all.return_value = mock_qs

        field = ModelPKChoiceField(queryset=mock_qs)
        result = field.to_python("42")
        assert result == 42
        mock_qs.get.assert_called_once_with(pk="42")

    def test_to_python_with_str_pk(self):
        mock_model = Mock()
        mock_obj = Mock()
        mock_obj.pk = "abc"
        mock_qs = Mock()
        mock_qs.get.return_value = mock_obj
        mock_qs.model = mock_model
        mock_qs.all.return_value = mock_qs

        field = ModelPKChoiceField(queryset=mock_qs)
        result = field.to_python("abc")
        assert result == "abc"

    def test_to_python_empty_value(self):
        mock_qs = Mock()
        mock_qs.all.return_value = mock_qs
        field = ModelPKChoiceField(queryset=mock_qs)
        assert field.to_python("") is None
        assert field.to_python(None) is None

    def test_to_python_invalid_choice(self):
        mock_model = Mock()
        mock_model.DoesNotExist = Exception
        mock_qs = Mock()
        mock_qs.get.side_effect = mock_model.DoesNotExist()
        mock_qs.model = mock_model
        mock_qs.all.return_value = mock_qs

        field = ModelPKChoiceField(queryset=mock_qs)
        with pytest.raises(forms.ValidationError):
            field.to_python("999")

    def test_to_python_with_to_field(self):
        mock_model = Mock()
        mock_obj = Mock()
        mock_obj.pk = 7
        mock_qs = Mock()
        mock_qs.get.return_value = mock_obj
        mock_qs.model = mock_model
        mock_qs.all.return_value = mock_qs

        field = ModelPKChoiceField(queryset=mock_qs, to_field_name="code")
        result = field.to_python("WGT")
        mock_qs.get.assert_called_once_with(code="WGT")
        assert result == 7

    def test_prepare_value_with_pk(self):
        mock_qs = Mock()
        field = ModelPKChoiceField(queryset=mock_qs)
        obj = Mock()
        obj.pk = 5
        assert field.prepare_value(obj) == 5

    def test_prepare_value_raw(self):
        mock_qs = Mock()
        field = ModelPKChoiceField(queryset=mock_qs)
        assert field.prepare_value("raw") == "raw"
