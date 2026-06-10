"""
Django admin integration for gRPC-backed resources.

``GrpcResourceAdmin`` is a ``ModelAdmin`` subclass that fetches data from a
remote gRPC service instead of the ORM.  It uses ``BaseGrpcResource`` for
metadata and ``BaseGrpcServiceAdapter`` for transport.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

from django.apps import apps
from django.contrib import messages
from django.contrib.admin import ModelAdmin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from django_admin_grpc.models import GrpcFakeQuerySet, ModelWrapper
from django_admin_grpc.paginator import GrpcPaginator, PagedResult

if TYPE_CHECKING:
    from django_admin_grpc.adapters import BaseGrpcServiceAdapter
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


def grpc_action(
    function: Callable[..., Any] | None = None,
    *,
    description: str = "",
    permissions: list[str] | None = None,
) -> Callable[..., Any]:
    """Decorator for gRPC admin actions.

    Wraps a method so it receives ``selected_pks`` (a list of primary keys)
    instead of a Django queryset, making it easier to work with gRPC bulk
    operations.

    Usage::

        class ProductAdmin(GrpcResourceAdmin):
            actions = ["activate_selected"]

            @grpc_action(description="Activate selected products")
            def activate_selected(self, request, selected_pks):
                updated, errors = self.apply_grpc_bulk_update(
                    request, selected_pks, {"active": True}
                )
                if updated:
                    messages.success(request, f"Activated {updated} product(s).")

    The decorated method is automatically exposed by Django's
    ``ModelAdmin.get_actions()`` when listed in ``actions``.

    Args:
        description: Human-readable label shown in the admin action dropdown.
            Defaults to the method name with underscores replaced by spaces.
        permissions: Optional list of permission codenames required to use
            this action (e.g. ``["change_product"]``).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, request: HttpRequest, queryset: Any) -> Any:
            selected_pks = self.get_grpc_selected_pks(request, queryset)
            return func(self, request, selected_pks)

        wrapper.short_description = description or getattr(  # type: ignore[attr-defined]
            func, "short_description", func.__name__.replace("_", " ").capitalize()
        )
        if permissions is not None:
            wrapper.allowed_permissions = permissions  # type: ignore[attr-defined]
        return wrapper

    if function is None:
        return decorator
    return decorator(function)


class GrpcChangeList(ChangeList):
    """
    Custom ``ChangeList`` that populates results by calling the adapter's
    ``list()`` method.
    """

    def __init__(
        self,
        request: HttpRequest,
        model: type,
        list_display: list[str],
        list_display_links: list[str],
        list_filter: list[Any],
        date_hierarchy: str | None,
        search_fields: list[str],
        list_select_related: bool,
        list_per_page: int,
        list_max_show_all: int,
        list_editable: list[str],
        model_admin: GrpcResourceAdmin,
        sortable_by: list[str],
        search_help_text: str,
    ):
        self._grpc_model_admin = model_admin
        self._grpc_list_filter = list_filter
        super().__init__(
            request,
            model,
            list_display,  # type: ignore[arg-type]
            list_display_links,  # type: ignore[arg-type]
            list_filter,
            date_hierarchy,
            search_fields,
            list_select_related,
            list_per_page,
            list_max_show_all,
            list_editable,
            model_admin,
            sortable_by,
            search_help_text,
        )
        filter_info = self.get_filters(request)
        self.filter_specs = filter_info[0]
        self.has_filters = filter_info[1]
        self.has_active_filters = (
            filter_info[4] if len(filter_info) > 4 else bool(filter_info[2])
        )

    def get_filters(self, request: HttpRequest) -> tuple:
        from django.contrib.admin import SimpleListFilter

        filter_specs: list[Any] = []
        lookup_params: dict[str, str] = {}
        params = dict(request.GET.items())

        if self._grpc_list_filter:
            for list_filter_item in self._grpc_list_filter:
                if isinstance(list_filter_item, type) and issubclass(
                    list_filter_item, SimpleListFilter
                ):
                    filter_spec: Any = list_filter_item(
                        request, params, self.model, self.model_admin  # type: ignore[arg-type]
                    )
                    filter_specs.append(filter_spec)
                    continue

                if isinstance(list_filter_item, str):
                    field_path = list_filter_item
                    filter_config: dict[str, Any] = {}

                    model_admin = cast(GrpcResourceAdmin, self.model_admin)
                    rc = model_admin.resource_class
                    if rc is None:
                        continue
                    if hasattr(model_admin, "grpc_filter_config"):
                        gfc = model_admin.grpc_filter_config
                        if isinstance(gfc, dict) and field_path not in gfc:
                            continue
                        if isinstance(gfc, dict):
                            filter_config = gfc.get(field_path, {})
                        else:
                            # list format
                            fc = rc.get_field_config(field_path)
                            filter_config = {"type": fc.type if fc else "text"}

                    field_type = filter_config.get("type", "text")
                    choices_list = filter_config.get("choices")

                    if field_type == "boolean" or (
                        field_type == "choices" and choices_list
                    ):
                        from django_admin_grpc.filters import create_grpc_filter_spec

                        filter_class = create_grpc_filter_spec(
                            field_path, field_type, choices_list
                        )
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": field_path.replace("_", " ").title(),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create filter for %s: %s", field_path, e
                            )
                    elif field_type in ("number_range", "date_range"):
                        from django_admin_grpc.filters import (
                            GrpcDateRangeFilter,
                            GrpcNumberRangeFilter,
                        )

                        filter_class = (
                            GrpcNumberRangeFilter
                            if field_type == "number_range"
                            else GrpcDateRangeFilter
                        )
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": filter_config.get(
                                    "label",
                                    field_path.replace("_", " ").title(),
                                ),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create %s filter for %s: %s",
                                field_type,
                                field_path,
                                e,
                            )
                    elif field_type == "multi_choices" and choices_list:
                        from django_admin_grpc.filters import create_grpc_filter_spec

                        filter_class = create_grpc_filter_spec(
                            field_path, field_type, choices_list
                        )
                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": field_path.replace("_", " ").title(),
                            },
                        )()
                        try:
                            filter_spec = filter_class(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create multi_choices filter for %s: %s",
                                field_path,
                                e,
                            )
                    elif field_type == "text":
                        from django_admin_grpc.filters import GrpcTextInputFilter

                        fake_field = type(
                            "FakeField",
                            (),
                            {
                                "name": field_path,
                                "verbose_name": filter_config.get(
                                    "label",
                                    field_path.replace("_", " ").title(),
                                ),
                            },
                        )()
                        try:
                            filter_spec = GrpcTextInputFilter(
                                fake_field,
                                request,
                                params,  # type: ignore[arg-type]
                                self.model,
                                self.model_admin,
                                field_path,
                            )
                            filter_specs.append(filter_spec)
                        except Exception as e:
                            logger.warning(
                                "Failed to create text filter for %s: %s",
                                field_path,
                                e,
                            )

        has_filters = bool(filter_specs)
        for filter_spec in filter_specs:
            try:
                for param in filter_spec.expected_parameters():
                    if param in request.GET:
                        lookup_params[param] = request.GET[param]
            except Exception:
                pass

        may_have_duplicates = False
        has_active_filters = bool(lookup_params)
        return (
            filter_specs,
            has_filters,
            lookup_params,
            may_have_duplicates,
            has_active_filters,
        )

    def get_queryset(  # type: ignore[override]
        self, request: HttpRequest
    ) -> GrpcFakeQuerySet:
        return GrpcFakeQuerySet(self.model)

    def get_results(self, request: HttpRequest) -> None:
        page_num = self.page_num or 1
        page_size = self.list_per_page
        filters = self._grpc_model_admin.get_grpc_filters(request)

        if getattr(self._grpc_model_admin, "grpc_cursor_pagination", False):
            cursor = request.GET.get("cursor")
            if cursor:
                filters["cursor"] = cursor

        search_query = request.GET.get("q", "")
        if search_query:
            filters["search"] = search_query

        try:
            result = self._grpc_model_admin.fetch_list(
                page=page_num, page_size=page_size, filters=filters
            )
            items = result.items if isinstance(result, PagedResult) else result.get("items", [])
            total = result.total if isinstance(result, PagedResult) else result.get("total", len(items))
            next_cursor = (
                result.next_cursor
                if isinstance(result, PagedResult)
                else result.get("next_cursor", None)
            )

            fake_model = self._grpc_model_admin._fake_model
            self.result_list = [
                ModelWrapper(item, fake_model._meta) for item in items
            ]
            self.result_count = total
            self.full_result_count = total
            self.can_show_all = False
            self.multi_page = self.result_count > page_size

            self.paginator = GrpcPaginator(
                self.result_list, page_size, self.result_count
            )

            if getattr(self._grpc_model_admin, "grpc_cursor_pagination", False):
                self.grpc_next_cursor = next_cursor
                if next_cursor:
                    params = request.GET.copy()
                    params["cursor"] = next_cursor
                    params.pop("p", None)
                    self.cursor_next_url = "?" + urlencode(params)
                else:
                    self.cursor_next_url = None  # type: ignore[assignment]
                from django_admin_grpc.settings import get_setting

                self.paginator.template_name = (
                    get_setting("DEFAULT_CURSOR_PAGINATION_TEMPLATE")
                    or "django_admin_grpc/cursor_pagination.html"
                )

        except Exception as e:
            logger.exception("Error fetching gRPC data: %s", e)
            self.result_list = []
            self.result_count = 0
            self.full_result_count = 0
            self.can_show_all = False
            self.multi_page = False
            self.paginator = GrpcPaginator([], page_size, 0)
            if getattr(self._grpc_model_admin, "grpc_cursor_pagination", False):
                self.cursor_next_url = None  # type: ignore[assignment]
            messages.info(request, "No data found or error fetching data.")


class GrpcResourceAdmin(ModelAdmin):
    """
    Admin class for resources fetched from a gRPC service.

    Subclasses **must** set:

    * ``resource_class`` – a ``BaseGrpcResource`` subclass.
    * ``service_name`` **or** ``adapter_class`` – tells the admin how to reach
      the remote service.

    Optional attributes:

    * ``grpc_filter_config`` – dict or list describing filterable fields.
    * ``grpc_form_fields`` – list of field names to expose in add/change forms.
    * ``grpc_enable_create`` / ``grpc_enable_update`` / ``grpc_enable_delete``
    * ``grpc_detail_fields`` – fields shown in the read-only detail section.
    * ``grpc_cursor_pagination`` – use cursor-based pagination.
    """

    resource_class: type[BaseGrpcResource] | None = None
    service_name: str = ""
    adapter_class: type[BaseGrpcServiceAdapter] | None = None

    verbose_name: str = ""
    verbose_name_plural: str = ""
    grpc_filter_config: dict[str, Any] | list[str] = {}
    grpc_form_fields: list[str] = []
    grpc_enable_create: bool = False
    grpc_enable_update: bool = False
    grpc_enable_delete: bool = False
    grpc_detail_fields: list[Any] = []
    grpc_cursor_pagination: bool = False

    def __init__(
        self, model: type[Any] | None = None, admin_site: Any | None = None
    ) -> None:
        if self.resource_class is None:
            raise ValueError(
                f"{self.__class__.__name__} must define resource_class"
            )
        self._resource_class: type[BaseGrpcResource] = self.resource_class
        self._fake_model = self._resource_class.admin_model()
        super().__init__(self._fake_model, admin_site)  # type: ignore[arg-type]
        self._adapter: BaseGrpcServiceAdapter | None = None

    # ── Template resolution ────────────────────────────────────────────────

    def _get_change_form_template(self) -> str:
        """Return the template path for add/change views.

        Resolution order:
        1. Resource Meta ``change_form_template``
        2. ``GRPC_ADMIN['DEFAULT_CHANGE_FORM_TEMPLATE']``
        3. Package default
        """
        resource_template = getattr(
            self._resource_class.Meta, "change_form_template", ""
        )
        if resource_template:
            return cast(str, resource_template)
        from django_admin_grpc.settings import get_setting

        setting_template = get_setting("DEFAULT_CHANGE_FORM_TEMPLATE")
        if setting_template:
            return cast(str, setting_template)
        return "django_admin_grpc/change_form.html"

    def _get_delete_confirm_template(self) -> str:
        """Return the template path for the delete confirmation view.

        Resolution order:
        1. Resource Meta ``delete_confirm_template``
        2. ``GRPC_ADMIN['DEFAULT_DELETE_CONFIRM_TEMPLATE']``
        3. Package default
        """
        resource_template = getattr(
            self._resource_class.Meta, "delete_confirm_template", ""
        )
        if resource_template:
            return cast(str, resource_template)
        from django_admin_grpc.settings import get_setting

        setting_template = get_setting("DEFAULT_DELETE_CONFIRM_TEMPLATE")
        if setting_template:
            return cast(str, setting_template)
        return "django_admin_grpc/delete_confirm.html"

    @classmethod
    def with_base(cls, base_admin_class: type) -> type[Any]:
        """Return a new admin class that inherits from the given base.

        Usage::

            class MyGrpcAdmin(GrpcResourceAdmin.with_base(UnfoldModelAdmin)):
                pass
        """
        return type(
            f"{cls.__name__}With{base_admin_class.__name__}",
            (cls, base_admin_class),
            {},
        )

    # ── Actions ────────────────────────────────────────────────────────────

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        if self._can_delete():
            actions["grpc_delete_selected"] = (  # type: ignore[assignment]
                self.__class__._grpc_delete_selected,
                "grpc_delete_selected",
                "Delete selected %(verbose_name_plural)s",
            )
        return actions

    def _grpc_delete_selected(self, request: HttpRequest, queryset: Any) -> None:
        selected_pks = self.get_grpc_selected_pks(request, queryset)
        deleted = 0
        errors = 0
        adapter = self.get_adapter()
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return
        for pk in selected_pks:
            try:
                adapter.delete(self._resource_class, pk=pk)
                deleted += 1
            except Exception as exc:
                logger.warning("gRPC delete failed for pk=%s: %s", pk, exc)
                errors += 1
        if deleted:
            messages.success(request, f"Successfully deleted {deleted} record(s).")
        if errors:
            messages.error(request, f"Failed to delete {errors} record(s).")

    _grpc_delete_selected.short_description = "Delete selected records"  # type: ignore[attr-defined]

    def get_grpc_selected_pks(self, request: HttpRequest, queryset: Any) -> list[Any]:
        selected = getattr(queryset, "_selected_pks", None) or request.POST.getlist("_selected_action")
        return list(selected or [])

    def apply_grpc_bulk_update(
        self,
        request: HttpRequest,
        queryset: Any,
        data: dict[str, Any],
    ) -> tuple[int, int]:
        adapter = self.get_adapter()
        if adapter is None:
            messages.error(request, "gRPC adapter not available.")
            return 0, 0

        # Support passing selected_pks directly (e.g. from @grpc_action)
        if isinstance(queryset, (list, tuple)):
            selected_pks = list(queryset)
        else:
            selected_pks = self.get_grpc_selected_pks(request, queryset)

        updated = 0
        errors = 0
        for pk in selected_pks:
            try:
                adapter.update(self._resource_class, pk, data)
                updated += 1
            except Exception as exc:
                logger.warning("gRPC bulk update failed for pk=%s: %s", pk, exc)
                errors += 1
        return updated, errors

    # ── Adapter plumbing ───────────────────────────────────────────────────

    def get_adapter(self) -> BaseGrpcServiceAdapter | None:
        """Return the gRPC adapter for this admin."""
        if self._adapter is not None:
            return self._adapter
        if self.adapter_class is not None:
            if isinstance(self.adapter_class, type):
                self._adapter = self.adapter_class()
                return self._adapter
            self._adapter = self.adapter_class
            return self._adapter
        if self.service_name:
            from django_admin_grpc.registry import adapter_registry

            self._adapter = adapter_registry.get_adapter(self.service_name)
            return self._adapter
        return None

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type[GrpcChangeList]:
        return GrpcChangeList

    def get_queryset(  # type: ignore[override]
        self, request: HttpRequest
    ) -> GrpcFakeQuerySet:
        return GrpcFakeQuerySet(self._resource_class)

    def get_grpc_filters(self, request: HttpRequest) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        cfg = self.grpc_filter_config
        is_dict_config = isinstance(cfg, dict)
        if cfg is not None:
            if is_dict_config:
                filterable_fields = set(cast(dict[str, Any], cfg).keys())
            else:
                filterable_fields = set(cfg)
        else:
            filterable_fields = None

        filter_config_dict: dict[str, Any] = (
            cast(dict[str, Any], cfg) if is_dict_config else {}
        )

        for key in request.GET:
            if key in {"p", "o", "all", "_changelist_filters", "e", "q", "cursor"}:
                continue

            if filterable_fields is not None:
                if is_dict_config:
                    base_key = key.split("__")[0]
                    if base_key not in filterable_fields:
                        continue
                    config = filter_config_dict.get(base_key, {})
                    field_type = config.get("type", "text") if isinstance(config, dict) else "text"
                    suffix = key[len(base_key) :] if key.startswith(base_key) else ""
                    if field_type in ("number_range", "date_range") and suffix and suffix not in {"__gte", "__lte", "__gt", "__lt"}:
                        continue
                    if field_type == "multi_choices" and suffix and suffix not in {"", "__exact", "__in"}:
                        continue
                else:
                    if key not in filterable_fields:
                        continue

            if is_dict_config:
                base_key = key.split("__")[0]
                config = filter_config_dict.get(base_key, {})
                field_type = config.get("type", "text") if isinstance(config, dict) else "text"
                if field_type == "multi_choices":
                    values = request.GET.getlist(key)
                    parsed: list[str] = []
                    for v in values:
                        parsed.extend(v.split(","))
                    parsed = [v.strip() for v in parsed if v.strip()]
                    if parsed:
                        filters[key] = parsed
                    continue

            filters[key] = request.GET[key]

        return filters

    def fetch_list(
        self,
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> PagedResult | dict[str, Any]:
        adapter = self.get_adapter()
        if adapter is None:
            logger.warning(
                "No gRPC adapter available for service: %s", self.service_name
            )
            return PagedResult(items=[])

        kwargs: dict[str, Any] = {"filters": filters or {}}
        if self.grpc_cursor_pagination:
            kwargs["page_size"] = page_size
        else:
            kwargs["page"] = page
            kwargs["page_size"] = page_size

        return adapter.list(self._resource_class, **kwargs)

    def fetch_one(self, pk: str) -> ModelWrapper | None:
        adapter = self.get_adapter()
        if adapter is None:
            return None
        instance = adapter.get(self._resource_class, pk=pk)
        if instance is None:
            return None
        return ModelWrapper(instance, self._fake_model._meta)

    # ── Permission helpers ─────────────────────────────────────────────────

    def _has_form_fields(self) -> bool:
        return bool(self.grpc_form_fields)

    def _adapter_supports_create(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_create

    def _adapter_supports_update(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_update

    def _adapter_supports_delete(self) -> bool:
        adapter = self.get_adapter()
        return adapter is not None and adapter.supports_delete

    def _can_create(self) -> bool:
        return self.grpc_enable_create and self._has_form_fields() and self._adapter_supports_create()

    def _can_update(self) -> bool:
        return self.grpc_enable_update and self._has_form_fields() and self._adapter_supports_update()

    def _can_delete(self) -> bool:
        return self.grpc_enable_delete and self._adapter_supports_delete()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return self.has_grpc_add_permission(request) and self._can_create()

    def has_change_permission(
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        return self.has_grpc_change_permission(request, obj=obj) and self.has_view_permission(request, obj=obj) and self._can_update()

    def has_delete_permission(
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        return self.has_grpc_delete_permission(request, obj=obj) and self._can_delete()

    def has_view_permission(
        self, request: HttpRequest, obj: Any = None
    ) -> bool:
        return self.has_grpc_view_permission(request, obj=obj)

    def has_grpc_add_permission(self, request: HttpRequest) -> bool:
        return True

    def has_grpc_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    def has_grpc_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    def has_grpc_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return True

    # ── Forms ──────────────────────────────────────────────────────────────

    def _build_form_class(self) -> type[Any]:
        from django_admin_grpc.forms import FormBuilder
        from django_admin_grpc.widgets import get_default_widgets

        return FormBuilder.build(
            self._resource_class,
            widgets=get_default_widgets(),
            field_names=self.grpc_form_fields or None,
        )

    def clean_grpc_data(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(data)
        for field_name, value in list(cleaned.items()):
            field_cleaner = getattr(self, f"clean_{field_name}", None)
            if callable(field_cleaner):
                cleaned[field_name] = field_cleaner(value)
        return self.clean(cleaned)

    def clean(self, data: dict[str, Any]) -> dict[str, Any]:
        return data

    def get_grpc_form_initial(self, obj: Any) -> dict[str, Any]:
        return {
            field_name: getattr(obj, field_name, None)
            for field_name in self.grpc_form_fields
        }

    def get_grpc_create_data(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return cleaned_data

    def get_grpc_update_data(
        self, obj: Any, cleaned_data: dict[str, Any]
    ) -> dict[str, Any]:
        return cleaned_data

    # ── Detail rows ────────────────────────────────────────────────────────

    def get_grpc_detail_fields(self) -> list[tuple[str, str]]:
        if self.grpc_detail_fields:
            if (
                isinstance(self.grpc_detail_fields[0], (list, tuple))
                and len(self.grpc_detail_fields[0]) == 2
            ):
                return list(self.grpc_detail_fields)
            fields: list[tuple[str, str]] = []
            for fn in self.grpc_detail_fields:
                fc = self._resource_class.get_field_config(str(fn))
                label = str(fc.label) if fc is not None else str(fn).replace("_", " ").title()
                fields.append((label, str(fn)))
            return fields
        return [
            (fc.label or fc.name, fc.name)
            for fc in self._resource_class.get_field_configs()
            if not fc.list_only
        ]

    def get_grpc_detail_rows(self, obj: Any) -> list[dict[str, Any]]:
        from django_admin_grpc.resources import FKFieldConfig

        rows: list[dict[str, Any]] = []
        for label, field_name in self.get_grpc_detail_fields():
            value = getattr(obj, field_name, None)
            config = self._resource_class.get_field_config(field_name)
            is_fk = config is not None and isinstance(config, FKFieldConfig)
            resolved_value = value
            if is_fk and value is not None:
                resolved = self.resolve_fk_value(field_name, config, value)
                if resolved is not None:
                    resolved_value = resolved
            rows.append(
                {
                    "label": label,
                    "field_name": field_name,
                    "value": resolved_value,
                    "is_boolean": isinstance(value, bool),
                    "is_fk": is_fk,
                }
            )
        return rows

    def resolve_fk_value(
        self,
        field_name: str,
        config: Any,
        fk_id: Any,
    ) -> str | None:
        from django_admin_grpc.resources import FKFieldConfig

        if config is None or not isinstance(config, FKFieldConfig):
            return fk_id if fk_id is not None else None  # type: ignore[return-value]
        if not config.display_field:
            return fk_id if fk_id is not None else None  # type: ignore[return-value]
        if not fk_id:
            return None

        # Django model lookup
        if getattr(config, "model", None):
            model_path = cast(str, config.model)
            try:
                app_label, model_name = model_path.split(".")
                model = apps.get_model(app_label, model_name)
                obj = model.objects.get(pk=fk_id)
                return str(getattr(obj, config.display_field, str(obj)))
            except (ValueError, LookupError) as e:
                logger.warning(
                    "resolve_fk_value: Django lookup failed for %s model=%s pk=%s: %s",
                    field_name,
                    model_path,
                    fk_id,
                    e,
                )
                return None
            except Exception as e:
                logger.warning(
                    "resolve_fk_value: Django lookup failed for %s model=%s pk=%s: %s",
                    field_name,
                    model_path,
                    fk_id,
                    e,
                )
                return None

        # gRPC service lookup
        if getattr(config, "service", None):
            service = cast(str, config.service)
            get_method = getattr(config, "get_method", "get")
            try:
                from django_admin_grpc.registry import adapter_registry

                adapter = adapter_registry.get_adapter(service)
                if adapter is None:
                    logger.warning(
                        "resolve_fk_value: No adapter for service=%s field=%s",
                        service,
                        field_name,
                    )
                    return None
                try:
                    result = getattr(adapter, get_method)(self._resource_class, pk=fk_id)
                except TypeError:
                    result = getattr(adapter, get_method)(self._resource_class, fk_id)
                if result is None:
                    return None
                return str(getattr(result, config.display_field, str(result)))
            except Exception as e:
                logger.warning(
                    "resolve_fk_value: gRPC lookup failed for %s service=%s pk=%s: %s",
                    field_name,
                    service,
                    fk_id,
                    e,
                )
                return None

        return str(fk_id) if fk_id is not None else None

    # ── Object retrieval ───────────────────────────────────────────────────

    def get_object(
        self,
        request: HttpRequest,
        object_id: str,
        from_field: str | None = None,
    ) -> ModelWrapper | None:
        return self.fetch_one(str(object_id))

    # ── Views ──────────────────────────────────────────────────────────────

    def changelist_view(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse:
        extra_context = extra_context or {}
        action = (
            "change"
            if self._can_update() or self._can_delete()
            else "view"
        )
        extra_context["title"] = (
            f"Select {self._fake_model._meta.verbose_name} to {action}"
        )
        response = super().changelist_view(request, extra_context)
        if self.grpc_cursor_pagination:
            if not hasattr(response, "context_data"):
                return response  # type: ignore[return-value]
            cl = response.context_data.get("cl")
            if cl and hasattr(cl, "cursor_next_url"):
                response.context_data["cursor_next_url"] = cl.cursor_next_url
        return response  # type: ignore[return-value]

    def add_view(
        self,
        request: HttpRequest,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_add_permission(request):
            raise PermissionDenied

        form_class = self._build_form_class()
        if request.method == "POST":
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    adapter = self.get_adapter()
                    if adapter is None:
                        messages.error(request, "gRPC adapter not available.")
                        return HttpResponseRedirect(
                            reverse(
                                f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                            )
                        )
                    cleaned_data = self.clean_grpc_data(form.cleaned_data)
                    adapter.create(
                        self._resource_class,
                        self.get_grpc_create_data(cleaned_data),
                    )
                    messages.success(
                        request,
                        f"Successfully created {self._fake_model._meta.verbose_name}.",
                    )
                    return HttpResponseRedirect(
                        reverse(
                            f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                        )
                    )
                except Exception as exc:
                    logger.exception("Error creating via gRPC: %s", exc)
                    messages.error(request, f"Error creating: {exc}")
        else:
            form = form_class()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Add {self._fake_model._meta.verbose_name}",
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "original": None,
            "object_id": None,
            "form": form,
            "detail_rows": [],
            "add": True,
            "change": False,
            "can_edit": True,
            "can_delete": False,
            "has_add_permission": True,
            "has_change_permission": False,
            "has_delete_permission": False,
            "has_view_permission": True,
            "has_editable_inline_admin_formsets": False,
            "inline_admin_formsets": [],
            "errors": [],
            "is_popup": False,
            "save_as": False,
            "show_save": True,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
            "show_delete_link": False,
            "media": self.media + form.media,
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            getattr(self, "grpc_add_form_template", None)
            or self._get_change_form_template(),
            context,
        )

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_view_permission(request):
            raise PermissionDenied

        obj = self.get_object(request, object_id)
        if obj is None:
            return cast(
                HttpResponseRedirect,
                self._get_obj_does_not_exist_redirect(  # type: ignore[attr-defined]
                    request, self._fake_model._meta, object_id
                ),
            )

        can_edit = self._can_update()
        can_delete = self._can_delete()
        form = None

        if request.method == "POST":
            if not can_edit:
                raise PermissionDenied
            form_class = self._build_form_class()
            form = form_class(request.POST)
            if form.is_valid():
                try:
                    adapter = self.get_adapter()
                    if adapter is None:
                        messages.error(request, "gRPC adapter not available.")
                        return HttpResponseRedirect(request.path)
                    cleaned_data = self.clean_grpc_data(form.cleaned_data)
                    adapter.update(
                        self._resource_class,
                        str(obj.pk),
                        self.get_grpc_update_data(obj, cleaned_data),
                    )
                    messages.success(
                        request,
                        f"Successfully updated {self._fake_model._meta.verbose_name}.",
                    )
                    return HttpResponseRedirect(request.path)
                except Exception as exc:
                    logger.exception("Error updating via gRPC: %s", exc)
                    messages.error(request, f"Error updating: {exc}")
        elif can_edit:
            form_class = self._build_form_class()
            form = form_class(initial=self.get_grpc_form_initial(obj))

        context = {
            **self.admin_site.each_context(request),
            "title": f"{self._fake_model._meta.verbose_name}: {obj}",
            "original": obj,
            "object_id": object_id,
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "form": form,
            "detail_rows": self.get_grpc_detail_rows(obj),
            "add": False,
            "change": True,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": can_edit,
            "has_delete_permission": can_delete,
            "has_view_permission": True,
            "has_editable_inline_admin_formsets": False,
            "inline_admin_formsets": [],
            "errors": [],
            "is_popup": False,
            "save_as": False,
            "show_save": can_edit,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
            "show_delete_link": can_delete,
            "media": self.media + (form.media if form else self.media.__class__()),
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            self._get_change_form_template(),
            context,
        )

    def delete_view(
        self,
        request: HttpRequest,
        object_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> TemplateResponse | HttpResponseRedirect:
        if not self.has_delete_permission(request):
            raise PermissionDenied

        obj = self.get_object(request, object_id)
        if obj is None:
            return cast(
                HttpResponseRedirect,
                self._get_obj_does_not_exist_redirect(  # type: ignore[attr-defined]
                    request, self._fake_model._meta, object_id
                ),
            )

        if request.method == "POST":
            try:
                adapter = self.get_adapter()
                if adapter is None:
                    messages.error(request, "gRPC adapter not available.")
                    return HttpResponseRedirect(
                        reverse(
                            f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                        )
                    )
                deleted = adapter.delete(self._resource_class, str(obj.pk))
                if deleted:
                    messages.success(
                        request,
                        f"Successfully deleted {self._fake_model._meta.verbose_name} '{obj}'.",
                    )
                else:
                    messages.warning(
                        request,
                        f"Delete returned False for {self._fake_model._meta.verbose_name} '{obj}'.",
                    )
            except Exception as exc:
                logger.exception("Error deleting via gRPC: %s", exc)
                messages.error(request, f"Error deleting: {exc}")
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self._fake_model._meta.app_label}_{self._fake_model._meta.model_name}_changelist"
                )
            )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Delete {self._fake_model._meta.verbose_name}",
            "original": obj,
            "object_id": object_id,
            "object_name": str(self._fake_model._meta.verbose_name),
            "opts": self._fake_model._meta,
            "app_label": self._fake_model._meta.app_label,
            "has_delete_permission": True,
            **(extra_context or {}),
        }
        return TemplateResponse(
            request,
            getattr(self, "grpc_delete_template", None)
            or self._get_delete_confirm_template(),
            context,
        )
