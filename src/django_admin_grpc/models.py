"""
Fake Django model infrastructure so that ``ModelAdmin`` can work without ORM tables.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, ClassVar

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models

if TYPE_CHECKING:
    from django_admin_grpc.audit import AuditEvent
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


class FakeModelMeta:
    """
    A stand-in for ``Options`` (``model._meta``) used by Django admin internals.
    """

    def __init__(
        self,
        resource_class: type[BaseGrpcResource],
        app_label: str,
        model_name: str,
        verbose_name: str,
        verbose_name_plural: str,
        pk_field_name: str = "id",
    ):
        self.resource_class = resource_class
        self.app_label = app_label
        self.model_name = model_name
        self.verbose_name = verbose_name
        self.verbose_name_plural = verbose_name_plural
        self.object_name = resource_class.__name__
        self.ordering: list[str] = []
        self.abstract = False
        self.swapped = False
        self.proxy = False
        self.concrete_model = None
        self.local_fields: list[Any] = []
        self.local_many_to_many: list[Any] = []
        self.private_fields: list[Any] = []
        self.fields: list[Any] = []
        self.many_to_many: list[Any] = []
        self._field_cache: dict[str, Any] = {}
        self._pk_field_name = pk_field_name
        self.is_composite_pk = False

        # Build a PK field object
        self.pk = self._make_pk_field(pk_field_name)

        # App config – create a fake one if the app is not registered
        try:
            self.app_config = apps.get_app_config(app_label)
        except LookupError:
            self.app_config = type(
                "FakeAppConfig",
                (),
                {
                    "label": app_label,
                    "name": app_label,
                    "verbose_name": app_label.title(),
                },
            )()

    def _make_pk_field(self, name: str) -> Any:
        return type(
            "PkField",
            (),
            {
                "name": name,
                "attname": name,
                "verbose_name": "ID",
                "is_relation": False,
                "related_model": None,
                "one_to_many": False,
                "one_to_one": False,
                "many_to_many": False,
                "many_to_one": False,
                "auto_created": True,
                "concrete": True,
                "editable": False,
                "hidden": False,
                "blank": False,
                "null": False,
                "primary_key": True,
                "unique": True,
                "choices": None,
                "help_text": "",
                "db_column": None,
                "db_tablespace": None,
                "default": None,
                "max_length": None,
                "remote_field": None,
                "column": name,
                "empty_values": [None, ""],
                "flatchoices": [],
                "validators": [],
                "error_messages": {},
                "decimal_places": None,
                "encoder": None,
            },
        )()

    def get_fields(self) -> list[Any]:
        return []

    def get_field(self, name: str) -> Any:
        """Return a field-like object for *name*, or raise ``FieldDoesNotExist``."""
        if name in self._field_cache:
            return self._field_cache[name]

        field_names = self.resource_class.get_field_names()
        if name not in field_names and name not in (self._pk_field_name, "pk", "id"):
            raise FieldDoesNotExist(f"{self.model_name} has no field named '{name}'")

        config = self.resource_class.get_field_config(name)
        field_obj = self._build_field(name, config)
        self._field_cache[name] = field_obj
        return field_obj

    def _build_field(self, name: str, config: Any | None) -> Any:
        from django.db import models as django_models

        from django_admin_grpc.resources import BooleanFieldConfig

        if config and isinstance(config, BooleanFieldConfig):
            bf = django_models.BooleanField(
                verbose_name=config.label if config else name.replace("_", " ").title(),
                null=True,
                blank=True,
            )
            bf.name = name
            bf.attname = name
            bf.column = name
            bf.concrete = True
            bf.auto_created = False
            bf.is_relation = False
            bf.related_model = None
            bf.one_to_many = False
            bf.one_to_one = False
            bf.many_to_many = False
            bf.many_to_one = False
            bf.editable = False
            bf.hidden = False
            bf.primary_key = False
            bf.remote_field = None
            bf.empty_values = [None, ""]
            return bf

        label = config.label if config else name.replace("_", " ").title()
        return type(
            "FakeField",
            (),
            {
                "name": name,
                "attname": name,
                "verbose_name": label,
                "is_relation": False,
                "related_model": None,
                "one_to_many": False,
                "one_to_one": False,
                "many_to_many": False,
                "many_to_one": False,
                "auto_created": False,
                "concrete": True,
                "editable": False,
                "hidden": False,
                "blank": True,
                "null": True,
                "primary_key": name in (self._pk_field_name, "pk"),
                "unique": name in (self._pk_field_name, "pk"),
                "choices": getattr(config, "choices", None) if config else None,
                "help_text": getattr(config, "help_text", "") if config else "",
                "db_column": None,
                "db_tablespace": None,
                "default": None,
                "max_length": getattr(config, "max_length", None) if config else None,
                "remote_field": None,
                "column": name,
                "empty_values": [None, ""],
                "flatchoices": [],
                "validators": [],
                "error_messages": {},
                "decimal_places": None,
                "encoder": None,
            },
        )()


class GrpcFakeQuerySet:
    """
    A minimal QuerySet stand-in so that Django admin actions can iterate over
    selected items without touching the database.
    """

    def __init__(
        self,
        model: type,
        selected_pks: list[Any] | None = None,
    ):
        self.model = model
        self._result_cache: list[Any] = []
        self._selected_pks = list(selected_pks) if selected_pks is not None else []

    def all(self) -> GrpcFakeQuerySet:
        return self

    def filter(self, **kwargs: Any) -> GrpcFakeQuerySet:
        pk_in = kwargs.get("pk__in")
        if pk_in is not None:
            return GrpcFakeQuerySet(self.model, selected_pks=list(pk_in))
        return GrpcFakeQuerySet(self.model, selected_pks=self._selected_pks)

    def order_by(self, *args: str) -> GrpcFakeQuerySet:
        return self

    def none(self) -> GrpcFakeQuerySet:
        return GrpcFakeQuerySet(self.model)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._result_cache)

    def __len__(self) -> int:
        return len(self._result_cache)

    def __bool__(self) -> bool:
        return True


class FakeModelBase:
    """Base class for dynamically-created fake Django model classes."""

    _meta: ClassVar[FakeModelMeta]
    _default_manager: ClassVar[GrpcFakeQuerySet]
    objects: ClassVar[GrpcFakeQuerySet]
    DoesNotExist: ClassVar[type[Exception]]
    MultipleObjectsReturned: ClassVar[type[Exception]]


class ModelWrapper:
    """
    Wraps a ``BaseGrpcResource`` instance so that it looks like a Django model
    instance to the admin templates (adds ``_meta`` and ``serializable_value``).
    """

    def __init__(
        self,
        instance: Any,
        fake_model_meta: FakeModelMeta,
        fk_display_cache: dict[str, dict[Any, Any]] | None = None,
    ) -> None:
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_meta", fake_model_meta)
        object.__setattr__(self, "_fk_display_cache", fk_display_cache or {})

    def __getattr__(self, name: str) -> Any:
        if name in ("_meta", "_instance", "_fk_display_cache"):
            return object.__getattribute__(self, name)
        cache = object.__getattribute__(self, "_fk_display_cache")
        if cache and name in cache:
            field_cache = cache[name]
            raw_value = getattr(self._instance, name, None)
            if isinstance(field_cache, dict):
                return field_cache.get(raw_value, raw_value)
            return field_cache
        return getattr(self._instance, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_meta", "_instance", "_fk_display_cache"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._instance, name, value)

    def __str__(self) -> str:
        return str(self._instance)

    def __repr__(self) -> str:
        return repr(self._instance)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ModelWrapper):
            return bool(self._instance == other._instance)
        return bool(self._instance == other)

    def __hash__(self) -> int:
        try:
            return hash(self._instance)
        except TypeError:
            return id(self._instance)

    def serializable_value(self, field_name: str) -> Any:
        """Called by admin list templates to retrieve a cell value."""
        return getattr(self._instance, field_name, None)


class GrpcAuditLog(models.Model):
    """Django model used by ``DjangoModelAuditBackend``."""

    id = models.BigAutoField(primary_key=True)
    resource_name = models.CharField(max_length=255, db_index=True)
    operation = models.CharField(max_length=32, db_index=True)
    pk_value = models.CharField(max_length=255, blank=True, db_index=True)
    user = models.CharField(max_length=255, blank=True, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    diff = models.JSONField(null=True, blank=True)
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    request_id = models.CharField(max_length=255, blank=True, db_index=True)
    extra = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["resource_name", "timestamp"], name="grpcaudit_resource_ts_idx"),
            models.Index(fields=["user", "timestamp"], name="grpcaudit_user_ts_idx"),
            models.Index(fields=["operation", "timestamp"], name="grpcaudit_op_ts_idx"),
        ]

    def to_audit_event(self) -> AuditEvent:
        from django_admin_grpc.audit import AuditEvent

        return AuditEvent(
            resource_name=self.resource_name,
            operation=self.operation,
            pk=self.pk_value or None,
            user=self.user or None,
            timestamp=self.timestamp,
            before=self.before,
            after=self.after,
            diff=self.diff,
            success=self.success,
            error=self.error or None,
            request_id=self.request_id or None,
            extra=self.extra,
        )
