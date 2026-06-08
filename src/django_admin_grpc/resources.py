"""
Base resource and field configuration for django-grpc-admin.

A ``BaseGrpcResource`` subclass declares the shape of a remote entity so that
Django admin can render lists, forms and detail views without touching the ORM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar

from django_admin_grpc.models import FakeModelBase, FakeModelMeta, GrpcFakeQuerySet

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class BaseFieldConfig:
    """Common metadata for every field on a ``BaseGrpcResource``."""

    name: str
    label: str | None = None
    required: bool = True
    help_text: str = ""
    initial: Any = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.label is None:
            self.label = self.name.replace("_", " ").title()

    @property
    def type(self) -> str:
        """Return the field type identifier (e.g. 'char', 'integer')."""
        raise NotImplementedError


@dataclass(kw_only=True)
class CharFieldConfig(BaseFieldConfig):
    """Configuration for a single-line text field."""

    max_length: int | None = None

    @property
    def type(self) -> str:
        return "char"


@dataclass(kw_only=True)
class TextFieldConfig(BaseFieldConfig):
    """Configuration for a multi-line text field."""

    @property
    def type(self) -> str:
        return "text"


@dataclass(kw_only=True)
class IntegerFieldConfig(BaseFieldConfig):
    """Configuration for an integer field."""

    @property
    def type(self) -> str:
        return "integer"


@dataclass(kw_only=True)
class FloatFieldConfig(BaseFieldConfig):
    """Configuration for a floating-point field."""

    @property
    def type(self) -> str:
        return "float"


@dataclass(kw_only=True)
class BooleanFieldConfig(BaseFieldConfig):
    """Configuration for a boolean field."""

    @property
    def type(self) -> str:
        return "boolean"


@dataclass(kw_only=True)
class ChoicesFieldConfig(BaseFieldConfig):
    """Configuration for a field with a fixed set of choices."""

    choices: list[tuple[str, str]] = field(default_factory=list)

    @property
    def type(self) -> str:
        return "choices"


@dataclass(kw_only=True)
class DateTimeFieldConfig(BaseFieldConfig):
    """Configuration for a datetime field."""

    @property
    def type(self) -> str:
        return "datetime"


@dataclass(kw_only=True)
class DateFieldConfig(BaseFieldConfig):
    """Configuration for a date field."""

    @property
    def type(self) -> str:
        return "date"


@dataclass(kw_only=True)
class FKFieldConfig(BaseFieldConfig):
    """Configuration for a foreign-key field."""

    model: str | None = None  # "app_label.ModelName"
    to_field: str | None = None
    display_field: str | None = None
    service: str | None = None
    get_method: str = "get"

    @property
    def type(self) -> str:
        return "fk"


class BaseGrpcResource:
    """
    Declarative base class for gRPC-backed entities.

    Subclasses **must** define:

    * ``Meta.app_label`` – used for URL reversing and app grouping.
    * ``fields`` – a ``list[BaseFieldConfig]`` describing every exposed column.

    Example::

        class NetworkRule(BaseGrpcResource):
            class Meta:
                app_label = "network"
                model_name = "networkrule"
                verbose_name = "Network Rule"
                verbose_name_plural = "Network Rules"
                pk_field = "rule_id"

            fields = [
                CharFieldConfig(name="rule_id", label="Rule ID"),
                CharFieldConfig(name="name"),
                BooleanFieldConfig(name="active"),
            ]
    """

    class Meta:
        app_label: str = ""
        model_name: str = ""
        verbose_name: str = ""
        verbose_name_plural: str = ""
        pk_field: str = "id"
        change_form_template: str = ""
        delete_confirm_template: str = ""

    fields: ClassVar[list[BaseFieldConfig]] = []

    def __init__(self, **kwargs: Any) -> None:
        for fc in self.fields:
            setattr(self, fc.name, kwargs.get(fc.name))

    @property
    def pk(self) -> Any:
        """Return the primary-key value for this instance."""
        pk_field = getattr(self.__class__.Meta, "pk_field", "id") or "id"
        return getattr(self, pk_field, None)

    def __str__(self) -> str:
        return str(self.pk)

    @classmethod
    def get_field_configs(cls) -> list[BaseFieldConfig]:
        """Return the list of field configurations for this resource."""
        return list(cls.fields)

    @classmethod
    def get_field_names(cls) -> list[str]:
        """Return a list of field names."""
        return [f.name for f in cls.fields]

    @classmethod
    def get_field_config(cls, name: str) -> BaseFieldConfig | None:
        """Return the ``BaseFieldConfig`` for *name* or ``None``."""
        for fc in cls.fields:
            if fc.name == name:
                return fc
        return None

    @classmethod
    def from_response(cls, response: Any) -> BaseGrpcResource:
        """
        Create an instance from a gRPC response object or mapping.

        Override this method when the response shape does not map 1-to-1 to
        field names.
        """
        kwargs: dict[str, Any] = {}
        for fc in cls.fields:
            source = fc.source or fc.name
            if isinstance(response, dict):
                kwargs[fc.name] = response.get(source)
            elif hasattr(response, source):
                kwargs[fc.name] = getattr(response, source)
            else:
                kwargs[fc.name] = None
        return cls(**kwargs)

    @classmethod
    def admin_model(cls) -> type[FakeModelBase]:
        """
        Create a fake Django model class for admin compatibility.

        The returned class has ``_meta``, ``_default_manager``, ``objects`` and
        ``DoesNotExist`` so that Django's ``ModelAdmin`` can work with it.
        """
        meta = cls.Meta
        app_label = getattr(meta, "app_label", "") or "grpc_admin"
        model_name = getattr(meta, "model_name", "") or cls.__name__.lower()
        verbose_name = getattr(meta, "verbose_name", "") or model_name.replace("_", " ").title()
        verbose_name_plural = getattr(meta, "verbose_name_plural", "") or f"{verbose_name}s"
        pk_field = getattr(meta, "pk_field", "") or "id"

        class FakeModel(FakeModelBase):
            pass

        FakeModel.__name__ = cls.__name__
        FakeModel._meta = FakeModelMeta(  # type: ignore[attr-defined]
            resource_class=cls,
            app_label=app_label,
            model_name=model_name,
            verbose_name=verbose_name,
            verbose_name_plural=verbose_name_plural,
            pk_field_name=pk_field,
        )
        FakeModel._default_manager = GrpcFakeQuerySet(cls)  # type: ignore[attr-defined]
        FakeModel.objects = GrpcFakeQuerySet(cls)  # type: ignore[attr-defined]
        FakeModel.DoesNotExist = type("DoesNotExist", (Exception,), {})  # type: ignore[attr-defined]
        FakeModel.MultipleObjectsReturned = type(  # type: ignore[attr-defined]
            "MultipleObjectsReturned", (Exception,), {}
        )

        return FakeModel

    @classmethod
    def build_form_class(cls, widgets: dict[str, Any] | None = None) -> type:
        """
        Build a Django ``Form`` class dynamically from field configs.

        Args:
            widgets: Optional mapping of field name to widget instance.

        Returns:
            A Django ``Form`` subclass.
        """

        from django_admin_grpc.forms import FormBuilder

        return FormBuilder.build(cls, widgets=widgets)
