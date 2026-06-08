"""
Registry for gRPC service adapters.

Provides a central place to register and look up ``BaseGrpcServiceAdapter``
instances by a short service name.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django_grpc_admin.adapters import BaseGrpcServiceAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    A simple registry that maps service names to adapter instances.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseGrpcServiceAdapter] = {}

    def register(self, service_name: str, adapter: BaseGrpcServiceAdapter) -> None:
        """Register an adapter under *service_name*."""
        self._adapters[service_name] = adapter
        logger.info("Registered gRPC adapter for service: %s", service_name)

    def unregister(self, service_name: str) -> None:
        """Remove a registered adapter."""
        if service_name in self._adapters:
            del self._adapters[service_name]
            logger.info("Unregistered gRPC adapter for service: %s", service_name)

    def get_adapter(self, service_name: str) -> BaseGrpcServiceAdapter | None:
        """Return the adapter for *service_name*, or ``None``."""
        return self._adapters.get(service_name)

    def list_services(self) -> list[str]:
        """Return all registered service names."""
        return list(self._adapters.keys())

    def clear(self) -> None:
        """Remove every adapter. Useful in tests."""
        self._adapters.clear()


# Module-level singleton – import this in your ``ready()`` handler.
adapter_registry = AdapterRegistry()
