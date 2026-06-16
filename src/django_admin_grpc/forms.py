"""
Form helpers for django-admin-grpc.

``FormBuilder`` constructs a Django ``Form`` subclass from a resource's
``BaseFieldConfig`` list.  ``ModelPKChoiceField`` is used for foreign-key fields
that reference real Django models.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django import forms
from django.apps import apps

if TYPE_CHECKING:
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


class ModelPKChoiceField(forms.ModelChoiceField):
    """
    A ``ModelChoiceField`` that returns the raw PK value instead of the model
    instance.  This is useful when the gRPC API expects an ID rather than an
    object.
    """

    def __init__(self, *args: Any, display_field: str | None = None, **kwargs: Any) -> None:
        self.display_field = display_field
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj: Any) -> str:
        if self.display_field:
            return str(getattr(obj, self.display_field, obj))
        return super().label_from_instance(obj)

    def to_python(self, value: Any) -> Any:
        if not value:
            return None
        qs = self.queryset
        if qs is None:
            return None
        try:
            obj = qs.get(**{self.to_field_name or "pk": value})
            pk = obj.pk
            # Only coerce to int if the model's PK field is an integer type
            pk_field = qs.model._meta.pk
            if pk_field and pk_field.get_internal_type() in (
                "AutoField",
                "BigAutoField",
                "SmallAutoField",
                "IntegerField",
                "BigIntegerField",
                "SmallIntegerField",
                "PositiveIntegerField",
                "PositiveBigIntegerField",
                "PositiveSmallIntegerField",
            ):
                try:
                    return int(pk)
                except (ValueError, TypeError):
                    pass
            return pk
        except (qs.model.DoesNotExist, ValueError, TypeError):
            raise forms.ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            ) from None

    def prepare_value(self, value: Any) -> Any:
        if hasattr(value, "pk"):
            return value.pk
        return value


class GrpcAdminForm(forms.Form):
    """
    Base form for gRPC-backed admin create/edit views.

    Subclasses may override ``get_create_data()`` and ``get_update_data()``
    to massage ``cleaned_data`` before it crosses the adapter boundary.
    """

    def get_create_data(self) -> dict[str, Any]:
        """Return the payload to send to ``adapter.create()``"""
        return dict(self.cleaned_data)

    def get_update_data(self) -> dict[str, Any]:
        """Return the payload to send to ``adapter.update()``"""
        return dict(self.cleaned_data)


class FormBuilder:
    """
    Builds a Django ``Form`` class from a ``BaseGrpcResource`` definition.
    """

    DEFAULT_WIDGETS: dict[str, str] = {
        "char": "django.forms.widgets.TextInput",
        "text": "django.forms.widgets.Textarea",
        "integer": "django.forms.widgets.NumberInput",
        "boolean": "django.forms.widgets.CheckboxInput",
        "choices": "django.forms.widgets.Select",
        "float": "django.forms.widgets.NumberInput",
        "fk": "django.forms.widgets.Select",
        "datetime": "django.forms.widgets.DateTimeInput",
        "date": "django.forms.widgets.DateInput",
    }

    @classmethod
    def build(
        cls,
        resource_class: type[BaseGrpcResource],
        widgets: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
    ) -> type[forms.Form]:
        """
        Return a ``Form`` subclass with one field per ``BaseFieldConfig``.

        Args:
            resource_class: The resource whose ``fields`` drive form generation.
            widgets: Optional dict mapping field name to a widget instance or
                dotted Python path.
            field_names: Optional list of field names to include. If ``None``,
                all fields are included.
        """
        if widgets is None:
            from django_admin_grpc.widgets import get_default_widgets

            widgets = get_default_widgets()

        form_fields: dict[str, forms.Field] = {}
        for fc in resource_class.get_field_configs():
            if field_names is not None and fc.name not in field_names:
                continue
            if fc.readonly or not fc.editable or fc.detail_only or fc.list_only:
                continue
            field = cls._make_form_field(fc, widgets)
            if field is not None:
                form_fields[fc.name] = field

        return type(
            f"{resource_class.__name__}Form",
            (GrpcAdminForm,),
            form_fields,
        )

    @classmethod
    def _make_form_field(
        cls,
        config: Any,
        widgets: dict[str, Any] | None = None,
    ) -> forms.Field | None:
        from django_admin_grpc.resources import (
            BaseFieldConfig,
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

        if not isinstance(config, BaseFieldConfig):
            logger.warning(
                "Unknown field config type for '%s', falling back to CharField",
                getattr(config, "name", "?"),
            )
            return forms.CharField(
                label=getattr(config, "label", "") or "",
                required=getattr(config, "required", True),
                help_text=getattr(config, "help_text", ""),
                initial=getattr(config, "initial", None),
                widget=cls._resolve_widget(config, widgets),
            )

        widget = cls._resolve_widget(config, widgets)

        if isinstance(config, CharFieldConfig):
            return forms.CharField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                max_length=config.max_length or 255,
                widget=widget,
            )
        if isinstance(config, TextFieldConfig):
            text_widget = widget or forms.Textarea(attrs={"rows": 4})
            if isinstance(text_widget, forms.Textarea):
                text_widget.attrs["rows"] = 4
            return forms.CharField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                widget=text_widget,
            )
        if isinstance(config, IntegerFieldConfig):
            return forms.IntegerField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                widget=widget,
            )
        if isinstance(config, BooleanFieldConfig):
            return forms.BooleanField(
                label=config.label,
                required=False,
                help_text=config.help_text,
                initial=config.initial,
                widget=widget,
            )
        if isinstance(config, ChoicesFieldConfig):
            choices = [("", "---")]
            if config.choices:
                choices.extend(config.choices)
            return forms.ChoiceField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                choices=choices,
                widget=widget,
            )
        if isinstance(config, FloatFieldConfig):
            return forms.FloatField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                widget=widget,
            )
        if isinstance(config, FKFieldConfig):
            return cls._make_fk_field(config, widget)
        if isinstance(config, (DateTimeFieldConfig, DateFieldConfig)):
            return forms.CharField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                widget=widget,
            )

        # Fallback – treat unknown types as plain CharField
        logger.warning(
            "Unknown field type '%s' for '%s', falling back to CharField",
            config.type,
            config.name,
        )
        return forms.CharField(
            label=config.label,
            required=config.required,
            help_text=config.help_text,
            initial=config.initial,
            widget=widget,
        )

    @classmethod
    def _resolve_widget(
        cls,
        config: Any,
        widgets: dict[str, Any] | None = None,
    ) -> Any | None:
        if not widgets:
            return None
        # Name-based lookup takes precedence
        if config.name in widgets:
            w = widgets[config.name]
            if isinstance(w, str):
                from django.utils.module_loading import import_string

                return import_string(w)()
            return w
        # Fall back to type-based lookup
        if config.type in widgets:
            w = widgets[config.type]
            if isinstance(w, type):
                return w()
            if isinstance(w, str):
                from django.utils.module_loading import import_string

                return import_string(w)()
            return w
        return None

    @classmethod
    def _make_fk_field(
        cls,
        config: Any,
        widget: Any | None = None,
    ) -> forms.Field:
        choices = cls._get_fk_choices(config)
        if choices is not None:
            return forms.ChoiceField(
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                initial=config.initial,
                choices=[("", "---"), *choices],
                widget=widget,
            )

        model_path = config.model or ""
        if model_path:
            try:
                app_label, model_name = model_path.split(".")
                related_model = apps.get_model(app_label, model_name)
            except (ValueError, LookupError) as exc:
                raise ValueError(
                    f"FK field '{config.name}': invalid model '{model_path}'. "
                    f"Expected 'app_label.ModelName'. Original error: {exc}"
                ) from exc
            return ModelPKChoiceField(
                queryset=related_model.objects.all(),
                label=config.label,
                required=config.required,
                help_text=config.help_text,
                to_field_name=config.to_field,
                display_field=config.display_field,
                empty_label="--- Select ---",
                widget=widget,
            )

        # Service/custom FKs must still render as selects. Users can populate
        # options with choices or choices_loader.
        return forms.ChoiceField(
            label=config.label,
            required=config.required,
            help_text=config.help_text or "Enter the related ID.",
            choices=[("", "---")],
            initial=config.initial,
            widget=widget,
        )

    @staticmethod
    def _get_fk_choices(config: Any) -> list[tuple[Any, str]] | None:
        if config.choices:
            return list(config.choices)
        if config.choices_loader is not None:
            return list(config.choices_loader())
        return None
