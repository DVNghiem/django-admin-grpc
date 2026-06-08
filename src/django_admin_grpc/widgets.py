"""
Default widget mappings for stock Django admin.

Override these at the project level by passing a ``widgets`` dict to
``resource.build_form_class(widgets={...})``.
"""
from django import forms

DEFAULT_WIDGETS: dict[str, type[forms.Widget]] = {
    "char": forms.TextInput,
    "text": forms.Textarea,
    "integer": forms.NumberInput,
    "boolean": forms.CheckboxInput,
    "choices": forms.Select,
    "float": forms.NumberInput,
    "fk": forms.Select,
    "datetime": forms.DateTimeInput,
    "date": forms.DateInput,
}


def get_widget_for_field_type(field_type: str) -> type[forms.Widget]:
    """Return the default widget class for *field_type*."""
    return DEFAULT_WIDGETS.get(field_type, forms.TextInput)


def get_default_widgets() -> dict[str, type[forms.Widget]]:
    """Return the default widget mapping. Can be overridden via GRPC_ADMIN['DEFAULT_WIDGETS'] setting."""
    from django_admin_grpc.settings import get_setting

    custom = get_setting("DEFAULT_WIDGETS")
    if custom:
        return custom  # type: ignore[no-any-return]
    return DEFAULT_WIDGETS
