"""
Generate ``BaseFieldConfig`` objects from a protobuf message descriptor.

This module makes it possible to declare a ``BaseGrpcResource`` by pointing it
at a protobuf message instead of hand-writing every field config.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django_admin_grpc.resources import (
    BaseFieldConfig,
    BooleanFieldConfig,
    CharFieldConfig,
    ChoicesFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
    JSONFieldConfig,
)

if TYPE_CHECKING:
    from google.protobuf.descriptor import FieldDescriptor

logger = logging.getLogger(__name__)


class ProtoFieldInspector:
    """
    Inspect a protobuf message descriptor and emit ``BaseFieldConfig`` instances.

    Options:

    * ``exclude`` -- field names to omit entirely.
    * ``readonly`` -- field names to mark as read-only.
    * ``pk_field`` -- field name to treat as the primary key (marked read-only).
    * ``field_overrides`` -- mapping of field name to a custom config instance.
    """

    # Map protobuf field types to the form field classes we generate.
    _SCALAR_MAP: dict[int, type[BaseFieldConfig]] = {
        1: FloatFieldConfig,  # TYPE_DOUBLE
        2: FloatFieldConfig,  # TYPE_FLOAT
        3: IntegerFieldConfig,  # TYPE_INT64
        4: IntegerFieldConfig,  # TYPE_UINT64
        5: IntegerFieldConfig,  # TYPE_INT32
        6: IntegerFieldConfig,  # TYPE_FIXED64
        7: IntegerFieldConfig,  # TYPE_FIXED32
        8: BooleanFieldConfig,  # TYPE_BOOL
        9: CharFieldConfig,  # TYPE_STRING
        12: CharFieldConfig,  # TYPE_BYTES
        13: IntegerFieldConfig,  # TYPE_UINT32
        15: IntegerFieldConfig,  # TYPE_SFIXED32
        16: IntegerFieldConfig,  # TYPE_SFIXED64
        17: IntegerFieldConfig,  # TYPE_SINT32
        18: IntegerFieldConfig,  # TYPE_SINT64
    }

    def __init__(
        self,
        descriptor: Any,
        *,
        exclude: list[str] | None = None,
        readonly: list[str] | None = None,
        pk_field: str = "id",
        field_overrides: dict[str, BaseFieldConfig] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.exclude = set(exclude or [])
        self.readonly = set(readonly or [])
        self.pk_field = pk_field
        self.field_overrides = field_overrides or {}

    def get_field_configs(self) -> list[BaseFieldConfig]:
        """Return a list of ``BaseFieldConfig`` objects for the message."""
        configs: list[BaseFieldConfig] = []
        for field in self.descriptor.fields:
            if field.name in self.exclude:
                continue
            configs.append(self._make_config(field))
        return configs

    def get_list_display(self) -> list[str]:
        """
        Return scalar field names suitable for ``list_display``.

        Nested message fields (including repeated fields and singular messages)
        are skipped.
        """
        result: list[str] = []
        for field in self.descriptor.fields:
            if field.name in self.exclude:
                continue
            if self._is_message_or_repeated(field):
                continue
            result.append(field.name)
        return result

    def get_search_fields(self) -> list[str]:
        """Return string-type field names suitable for ``search_fields``."""
        result: list[str] = []
        for field in self.descriptor.fields:
            if field.name in self.exclude:
                continue
            if self._is_message_or_repeated(field):
                continue
            if field.type == 9:  # TYPE_STRING
                result.append(field.name)
        return result

    def _make_config(self, field: FieldDescriptor) -> BaseFieldConfig:
        if field.name in self.field_overrides:
            return self.field_overrides[field.name]

        if field.type == 14:  # TYPE_ENUM
            return self._make_enum_config(field)

        if self._is_message_or_repeated(field):
            return JSONFieldConfig(
                name=field.name,
                readonly=(field.name in self.readonly or field.name == self.pk_field),
            )

        config_class = self._SCALAR_MAP.get(field.type, CharFieldConfig)
        kwargs: dict[str, Any] = {
            "name": field.name,
            "required": not field.has_presence,  # optional/proto3 fields can be empty
            "readonly": (field.name in self.readonly or field.name == self.pk_field),
        }
        if config_class is CharFieldConfig:
            kwargs["max_length"] = None

        return config_class(**kwargs)

    def _make_enum_config(self, field: FieldDescriptor) -> ChoicesFieldConfig:
        enum_descriptor = field.enum_type
        choices: list[tuple[Any, str]] = []
        if enum_descriptor is not None:
            for value in enum_descriptor.values:
                choices.append((value.number, value.name))
        return ChoicesFieldConfig(
            name=field.name,
            choices=choices,
            required=not field.has_presence,
            readonly=(field.name in self.readonly or field.name == self.pk_field),
        )

    @staticmethod
    def _is_message_or_repeated(field: Any) -> bool:
        if getattr(field, "is_repeated", False):
            return True
        return field.type == 11  # TYPE_MESSAGE
