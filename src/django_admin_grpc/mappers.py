"""
Request/response mapper for transforming between Django forms and gRPC messages.

Mappers live between the admin layer and the adapter layer.  They translate
Django form ``cleaned_data`` into gRPC request messages and gRPC responses
into ``BaseGrpcResource`` instances.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


class BaseGrpcMapper(ABC):
    """
    Abstract mapper that converts between Django/Python land and gRPC land.

    Subclasses typically know the concrete protobuf message types for a service
    and implement the three transformation methods below.
    """

    @abstractmethod
    def to_create_request(
        self,
        resource_class: type[BaseGrpcResource],
        cleaned_data: dict[str, Any],
    ) -> Any:
        """
        Convert form ``cleaned_data`` into a gRPC *Create* request message.

        Returns:
            A protobuf message instance or plain dict suitable for the adapter.
        """
        ...

    @abstractmethod
    def to_update_request(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
        cleaned_data: dict[str, Any],
    ) -> Any:
        """
        Convert form ``cleaned_data`` into a gRPC *Update* request message.
        """
        ...

    @abstractmethod
    def from_response(
        self,
        resource_class: type[BaseGrpcResource],
        response: Any,
    ) -> BaseGrpcResource:
        """
        Convert a gRPC response message into a ``BaseGrpcResource`` instance.

        The default implementation delegates to ``resource_class.from_response()``.
        """
        ...

    @abstractmethod
    def to_list_request(
        self,
        resource_class: type[BaseGrpcResource],
        page: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        """
        Convert list parameters into a gRPC *List* request message.
        """
        ...

    @abstractmethod
    def from_list_response(
        self,
        resource_class: type[BaseGrpcResource],
        response: Any,
    ) -> dict[str, Any]:
        """
        Convert a gRPC *List* response into a dict with keys:
        ``items``, ``total``, ``next_cursor``.
        """
        ...


class DefaultGrpcMapper(BaseGrpcMapper):
    """
    A pass-through mapper that assumes the adapter works with plain dicts
    and that ``resource_class.from_response()`` can handle the response.
    """

    def to_create_request(
        self,
        resource_class: type[BaseGrpcResource],
        cleaned_data: dict[str, Any],
    ) -> Any:
        return cleaned_data

    def to_update_request(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
        cleaned_data: dict[str, Any],
    ) -> Any:
        return {"pk": pk, **cleaned_data}

    def from_response(
        self,
        resource_class: type[BaseGrpcResource],
        response: Any,
    ) -> BaseGrpcResource:
        return resource_class.from_response(response)

    def to_list_request(
        self,
        resource_class: type[BaseGrpcResource],
        page: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        return {
            "page": page,
            "page_size": page_size,
            "filters": filters or {},
        }

    def from_list_response(
        self,
        resource_class: type[BaseGrpcResource],
        response: Any,
    ) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        # Assume protobuf-like object
        items = list(getattr(response, "items", []))
        total = getattr(response, "total", len(items))
        next_cursor = getattr(response, "next_cursor", None)
        return {
            "items": items,
            "total": total,
            "next_cursor": next_cursor,
        }
