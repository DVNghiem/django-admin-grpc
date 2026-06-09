"""
django-admin-grpc

A reusable Django package for creating admin interfaces backed by gRPC services.
"""

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import GrpcResourceAdmin, grpc_action
from django_admin_grpc.exceptions import (
    GrpcAdminError,
    GrpcDeadlineExceededError,
    GrpcInvalidArgumentError,
    GrpcNotFoundError,
    GrpcPermissionDeniedError,
    GrpcUnavailableError,
)
from django_admin_grpc.filters import (
    GrpcBooleanFieldListFilter,
    GrpcChoicesFieldListFilter,
    GrpcSimpleListFilter,
    GrpcTextInputFilter,
    create_grpc_filter_spec,
)
from django_admin_grpc.guide import GUIDE
from django_admin_grpc.mappers import BaseGrpcMapper
from django_admin_grpc.paginator import GrpcPaginator, PagedResult
from django_admin_grpc.registry import AdapterRegistry, adapter_registry
from django_admin_grpc.resources import (
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

__version__ = "0.2.0"

__all__ = [
    "GUIDE",
    "GrpcResourceAdmin",
    "grpc_action",
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
