"""
List filters for gRPC-backed admin changelists.

These filters do not touch the ORM – they only read query-string parameters
so that ``GrpcResourceAdmin.get_grpc_filters()`` can forward them to the
remote service.
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.admin import FieldListFilter, SimpleListFilter

logger = logging.getLogger(__name__)


class GrpcFieldListFilter(FieldListFilter):
    """Base filter that avoids any database access."""

    def __init__(
        self,
        field: Any,
        request: Any,
        params: dict[str, str],
        model: Any,
        model_admin: Any,
        field_path: str,
    ):
        self.field = field
        self.field_path = field_path
        self.title = getattr(
            field, "verbose_name", field_path.replace("_", " ").title()
        ) or field_path.replace("_", " ").title()
        # Bypass FieldListFilter.__init__ to avoid DB lookups
        super(FieldListFilter, self).__init__(
            request, params, model, model_admin
        )

    def expected_parameters(self) -> list[str]:
        return [self.field_path, f"{self.field_path}__exact"]

    def choices(self, changelist: Any) -> Any:
        return []


class GrpcBooleanFieldListFilter(GrpcFieldListFilter):
    """Filter for boolean fields – Yes / No / All."""

    def __init__(
        self,
        field: Any,
        request: Any,
        params: dict[str, str],
        model: Any,
        model_admin: Any,
        field_path: str,
    ):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg = f"{field_path}__exact"
        self.lookup_val = request.GET.get(self.lookup_kwarg)

    def expected_parameters(self) -> list[str]:
        return [self.lookup_kwarg]

    def choices(self, changelist: Any) -> Any:
        yield {
            "selected": self.lookup_val is None,
            "query_string": changelist.get_query_string(
                remove=[self.lookup_kwarg]
            ),
            "display": "All",
        }
        for lookup, title in (("1", "Yes"), ("0", "No")):
            yield {
                "selected": self.lookup_val == lookup,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: lookup}
                ),
                "display": title,
            }


class GrpcChoicesFieldListFilter(GrpcFieldListFilter):
    """Filter for fields with a fixed set of choices."""

    def __init__(
        self,
        field: Any,
        request: Any,
        params: dict[str, str],
        model: Any,
        model_admin: Any,
        field_path: str,
        choices: list[tuple[str, str]] | None = None,
    ):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.lookup_kwarg = f"{field_path}__exact"
        self.lookup_val = request.GET.get(self.lookup_kwarg)
        self._choices = choices or []

    def expected_parameters(self) -> list[str]:
        return [self.lookup_kwarg]

    def choices(self, changelist: Any) -> Any:
        yield {
            "selected": self.lookup_val is None,
            "query_string": changelist.get_query_string(
                remove=[self.lookup_kwarg]
            ),
            "display": "All",
        }
        for lookup, title in self._choices:
            yield {
                "selected": self.lookup_val == lookup,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: lookup}
                ),
                "display": title,
            }


class GrpcSimpleListFilter(SimpleListFilter):
    """
    Base class for custom gRPC filters modelled on Django's ``SimpleListFilter``.

    Subclasses should define ``title``, ``parameter_name`` and implement
    ``lookups()``.
    """

    title = ""
    parameter_name = ""

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[str, str]]:
        return []

    def queryset(self, request: Any, queryset: Any) -> Any:
        # No-op – filtering is handled by the admin's get_grpc_filters()
        return queryset


class GrpcTextInputFilter(FieldListFilter):
    """
    A free-text filter that renders a text input.

    The template path is left blank so that Django admin falls back to its
    default filter rendering.  Projects using ``django-unfold`` can subclass
    and set ``template`` to ``'unfold/filters/filters_field.html'``.
    """

    template = ""

    def __init__(
        self,
        field: Any,
        request: Any,
        params: dict[str, str],
        model: Any,
        model_admin: Any,
        field_path: str,
    ):
        self.field = field
        self.field_path = field_path
        self._label = getattr(
            field, "verbose_name", field_path.replace("_", " ").title()
        )
        self.lookup_kwarg = field_path
        self.lookup_val = params.get(self.lookup_kwarg, "")
        super(FieldListFilter, self).__init__(
            request, params, model, model_admin
        )
        if self.lookup_val:
            self.used_parameters[self.lookup_kwarg] = self.lookup_val

    @property
    def title(self) -> str:
        return self._label

    def expected_parameters(self) -> list[str]:
        return [self.lookup_kwarg]

    def has_output(self) -> bool:
        return True

    def choices(self, changelist: Any) -> Any:
        yield {
            "name": self.lookup_kwarg,
            "label": f" By {self._label} ",
            "value": self.lookup_val,
        }


def create_grpc_filter_spec(
    field_name: str,
    field_type: str = "text",
    choices: list[tuple[str, str]] | None = None,
) -> type[FieldListFilter]:
    """
    Factory that returns a ``FieldListFilter`` subclass for *field_name*.

    Args:
        field_name: The query-string parameter / field name.
        field_type: ``'boolean'``, ``'choices'`` or ``'text'``.
        choices: Required when *field_type* is ``'choices'``.

    Returns:
        A filter class ready for ``list_filter``.
    """

    class DynamicGrpcFilter(FieldListFilter):
        def __init__(
            self,
            field: Any,
            request: Any,
            params: dict[str, str],
            model: Any,
            model_admin_instance: Any,
            field_path: str,
        ):
            self.field = field
            self.field_path = field_path
            self.title = field_path.replace("_", " ").title()
            self.lookup_kwarg = f"{field_path}__exact"
            self.lookup_val = params.get(self.lookup_kwarg)
            self.empty_value_display = (
                model_admin_instance.get_empty_value_display()
                if hasattr(model_admin_instance, "get_empty_value_display")
                else "-"
            )
            super(FieldListFilter, self).__init__(
                request, params, model, model_admin_instance
            )

        def expected_parameters(self) -> list[str]:
            return [self.lookup_kwarg]

        def has_output(self) -> bool:
            return True

        def choices(self, changelist: Any) -> Any:
            yield {
                "selected": self.lookup_val is None,
                "query_string": changelist.get_query_string(
                    remove=[self.lookup_kwarg]
                ),
                "display": "All",
            }

            if field_type == "boolean":
                filter_choices = [("1", "Yes"), ("0", "No")]
            elif field_type == "choices" and choices:
                filter_choices = choices
            else:
                return

            for lookup, title in filter_choices:
                yield {
                    "selected": self.lookup_val == lookup,
                    "query_string": changelist.get_query_string(
                        {self.lookup_kwarg: lookup}
                    ),
                    "display": title,
                }

    return DynamicGrpcFilter
