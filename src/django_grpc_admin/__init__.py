"""
django-grpc-admin

A reusable Django package for creating admin interfaces backed by gRPC services.
"""

from django_grpc_admin.adapters import BaseGrpcServiceAdapter
from django_grpc_admin.exceptions import (
    GrpcAdminError,
    GrpcDeadlineExceededError,
    GrpcInvalidArgumentError,
    GrpcNotFoundError,
    GrpcPermissionDeniedError,
    GrpcUnavailableError,
)
from django_grpc_admin.filters import (
    GrpcBooleanFieldListFilter,
    GrpcChoicesFieldListFilter,
    GrpcSimpleListFilter,
    GrpcTextInputFilter,
    create_grpc_filter_spec,
)
from django_grpc_admin.mappers import BaseGrpcMapper
from django_grpc_admin.paginator import GrpcPaginator, PagedResult
from django_grpc_admin.registry import AdapterRegistry, adapter_registry
from django_grpc_admin.resources import (
    BaseFieldConfig,
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

__version__ = "0.1.0"

__all__ = [
    "BaseFieldConfig",
    "BaseGrpcResource",
    "BaseGrpcServiceAdapter",
    "BaseGrpcMapper",
    "BooleanFieldConfig",
    "CharFieldConfig",
    "ChoicesFieldConfig",
    "DateFieldConfig",
    "DateTimeFieldConfig",
    "FKFieldConfig",
    "FloatFieldConfig",
    "IntegerFieldConfig",
    "TextFieldConfig",
    "GrpcAdminError",
    "GrpcNotFoundError",
    "GrpcPermissionDeniedError",
    "GrpcInvalidArgumentError",
    "GrpcUnavailableError",
    "GrpcDeadlineExceededError",
    "GrpcPaginator",
    "PagedResult",
    "GrpcBooleanFieldListFilter",
    "GrpcChoicesFieldListFilter",
    "GrpcSimpleListFilter",
    "GrpcTextInputFilter",
    "create_grpc_filter_spec",
    "AdapterRegistry",
    "adapter_registry",
]
