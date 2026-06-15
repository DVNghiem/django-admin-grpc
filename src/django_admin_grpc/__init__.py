"""
django-admin-grpc

A reusable Django package for creating admin interfaces backed by gRPC services.
"""

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import (
    AsyncGrpcResourceAdmin,
    GrpcResourceAdmin,
    grpc_action,
    run_async,
)
from django_admin_grpc.async_adapter import (
    AsyncAdapterRegistry,
    BaseAsyncGrpcServiceAdapter,
    async_adapter_registry,
)
from django_admin_grpc.exceptions import (
    GrpcAbortedError,
    GrpcAdminError,
    GrpcAlreadyExistsError,
    GrpcCancelledError,
    GrpcDeadlineExceededError,
    GrpcFailedPreconditionError,
    GrpcInvalidArgumentError,
    GrpcNotFoundError,
    GrpcPermissionDeniedError,
    GrpcResourceExhaustedError,
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
from django_admin_grpc.pool import GrpcChannelPool
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

__version__ = "0.2.2"

__all__ = [
    "GUIDE",
    "GrpcResourceAdmin",
    "AsyncGrpcResourceAdmin",
    "grpc_action",
    "run_async",
    "BaseFieldConfig",
    "BaseGrpcResource",
    "BaseGrpcServiceAdapter",
    "BaseAsyncGrpcServiceAdapter",
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
    "GrpcAlreadyExistsError",
    "GrpcNotFoundError",
    "GrpcPermissionDeniedError",
    "GrpcInvalidArgumentError",
    "GrpcUnavailableError",
    "GrpcDeadlineExceededError",
    "GrpcResourceExhaustedError",
    "GrpcFailedPreconditionError",
    "GrpcAbortedError",
    "GrpcCancelledError",
    "GrpcPaginator",
    "PagedResult",
    "GrpcBooleanFieldListFilter",
    "GrpcChoicesFieldListFilter",
    "GrpcSimpleListFilter",
    "GrpcTextInputFilter",
    "create_grpc_filter_spec",
    "AdapterRegistry",
    "adapter_registry",
    "AsyncAdapterRegistry",
    "async_adapter_registry",
    "GrpcChannelPool",
]
