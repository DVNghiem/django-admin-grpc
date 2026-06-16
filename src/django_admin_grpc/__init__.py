"""
django-admin-grpc

A reusable Django package for creating admin interfaces backed by gRPC services.
"""

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.admin import (
    AsyncGrpcResourceAdmin,
    BulkActionMixin,
    GrpcResourceAdmin,
    bulk_grpc_action,
    grpc_action,
    run_async,
)
from django_admin_grpc.async_adapter import (
    AsyncAdapterRegistry,
    BaseAsyncGrpcServiceAdapter,
    async_adapter_registry,
)
from django_admin_grpc.cache import CachedAdapterMixin, GrpcAdminCache
from django_admin_grpc.exceptions import (
    GrpcAbortedError,
    GrpcAdminError,
    GrpcAlreadyExistsError,
    GrpcBatchPartialError,
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
from django_admin_grpc.utils import chunked

__version__ = "0.2.2"

__all__ = [
    "GUIDE",
    "GrpcResourceAdmin",
    "AsyncGrpcResourceAdmin",
    "BulkActionMixin",
    "grpc_action",
    "bulk_grpc_action",
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
    "GrpcBatchPartialError",
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
    "GrpcAdminCache",
    "CachedAdapterMixin",
    "chunked",
]
