"""
Registry for gRPC service adapters.

Provides a central place to register and look up ``BaseGrpcServiceAdapter``
instances by a short service name.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django_admin_grpc.adapters import BaseGrpcServiceAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    A thread-safe registry that maps service names to adapter instances.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseGrpcServiceAdapter] = {}
        self._lock = threading.RLock()
        self._frozen = False

    def register(self, service_name: str, adapter: BaseGrpcServiceAdapter) -> None:
        """Register an adapter under *service_name*."""
        if self._frozen:
            raise RuntimeError("Adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Adapter registry is frozen")
            self._adapters[service_name] = adapter
        logger.info("Registered gRPC adapter for service: %s", service_name)

    def unregister(self, service_name: str) -> None:
        """Remove a registered adapter."""
        if self._frozen:
            raise RuntimeError("Adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Adapter registry is frozen")
            if service_name in self._adapters:
                del self._adapters[service_name]
        logger.info("Unregistered gRPC adapter for service: %s", service_name)

    def get_adapter(self, service_name: str) -> BaseGrpcServiceAdapter | None:
        """Return the adapter for *service_name*, or ``None``."""
        if self._frozen:
            return self._adapters.get(service_name)
        with self._lock:
            return self._adapters.get(service_name)

    def list_services(self) -> list[str]:
        """Return all registered service names."""
        if self._frozen:
            return list(self._adapters.keys())
        with self._lock:
            return list(self._adapters.keys())

    def clear(self) -> None:
        """Remove every adapter. Useful in tests."""
        if self._frozen:
            raise RuntimeError("Adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Adapter registry is frozen")
            self._adapters.clear()

    def freeze(self) -> None:
        """Make the registry read-only."""
        with self._lock:
            self._frozen = True

    def close_all(self) -> None:
        """Close every registered adapter's channel."""
        if self._frozen:
            adapters = list(self._adapters.values())
        else:
            with self._lock:
                adapters = list(self._adapters.values())
        for adapter in adapters:
            try:
                adapter.close()
            except Exception:
                logger.exception(
                    "Error closing adapter for service: %s", adapter.service_name
                )


# Module-level singleton – import this in your ``ready()`` handler.
adapter_registry = AdapterRegistry()
