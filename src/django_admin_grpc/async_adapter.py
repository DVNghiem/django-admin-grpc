"""
Async gRPC service adapter support built on ``grpc.aio``.

Provides an asyncio-native adapter base class and registry that mirror the
synchronous ``BaseGrpcServiceAdapter`` and ``AdapterRegistry`` APIs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import grpc

from django_admin_grpc.exceptions import map_grpc_error
from django_admin_grpc.paginator import PagedResult

if TYPE_CHECKING:
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


_aio_initialized = False
_aio_init_lock = threading.Lock()


def ensure_aio_initialized() -> None:
    """
    Idempotently initialize the gRPC async runtime.

    Older ``grpcio`` versions expose ``grpc.aio.init_grpc_aio()`` while newer
    ones initialize automatically.  The function only calls ``init_grpc_aio``
    when an event loop is already running so it can be used safely from
    synchronous code paths that merely hold async adapters.
    """
    global _aio_initialized
    if _aio_initialized:
        return
    with _aio_init_lock:
        if _aio_initialized:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; defer initialization to the first async use.
            return
        init = getattr(grpc.aio, "init_grpc_aio", None)
        if init is not None:
            try:
                init()
            except RuntimeError as exc:
                # Already initialized in this interpreter.
                if "already initialized" not in str(exc).lower():
                    raise
        _aio_initialized = True


class BaseAsyncGrpcServiceAdapter(ABC):
    """
    Async interface between Django admin and a remote gRPC service.

    Subclasses implement async ``list`` and ``get``.  The channel is created
    lazily on first use and protected by an asyncio lock.
    """

    service_name: str = ""
    target: str = ""
    credentials: grpc.ChannelCredentials | None = None

    def __init__(self) -> None:
        self._channel: grpc.aio.Channel | None = None
        self._channel_lock = asyncio.Lock()
        ensure_aio_initialized()

    @abstractmethod
    async def list(
        self,
        resource_class: type[BaseGrpcResource],
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> PagedResult:
        """Fetch a page of entities asynchronously."""
        ...

    @abstractmethod
    async def get(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> BaseGrpcResource | None:
        """Fetch a single entity by primary key asynchronously."""
        ...

    async def batch_get(
        self,
        resource_class: type[BaseGrpcResource],
        pks: Sequence[Any],
    ) -> dict[Any, BaseGrpcResource | None]:
        """
        Fetch multiple entities by primary key asynchronously.

        The default implementation issues ``get()`` calls concurrently.
        """
        result: dict[Any, BaseGrpcResource | None] = {}
        if not pks:
            return result

        async def _fetch(pk: Any) -> tuple[Any, BaseGrpcResource | None]:
            return pk, await self.get(resource_class, str(pk))

        fetched = await asyncio.gather(*(_fetch(pk) for pk in pks))
        for pk, item in fetched:
            result[pk] = item
        return result

    async def create(
        self,
        resource_class: type[BaseGrpcResource],
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Create a new entity via gRPC asynchronously."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support create")

    async def update(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Update an existing entity via gRPC asynchronously."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support update")

    async def delete(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> bool:
        """Delete an entity via gRPC asynchronously."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support delete")

    # ── Bulk operations (chunked fallback) ────────────────────────────────

    batch_size: int = 100

    async def bulk_create(
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:
        """
        Create multiple entities via gRPC, chunked.

        The default implementation awaits ``create()`` per item in chunks of
        ``batch_size`` (defaulting to ``self.batch_size``).  Adapters that
        expose a true bulk create endpoint should override this.

        On partial failure, raises :class:`GrpcBatchPartialError` with the
        succeeded and failed entries.
        """
        from django_admin_grpc.exceptions import GrpcBatchPartialError
        from django_admin_grpc.utils import chunked

        if not items:
            return []
        size = batch_size if batch_size is not None else self.batch_size
        created: list[BaseGrpcResource] = []
        succeeded_inputs: list[dict[str, Any]] = []
        failed: dict[int, Exception] = {}
        # Resource name is included in logs so multiple resources can be
        # disambiguated, but the raw input payload is intentionally not
        # logged — it may contain sensitive fields.
        resource_name = getattr(resource_class, "__name__", str(resource_class))
        for chunk in chunked(items, size):
            for data in chunk:
                # Stable key: the index of the input across all chunks.
                index = len(succeeded_inputs) + len(failed)
                try:
                    created.append(await self.create(resource_class, data))
                    succeeded_inputs.append(data)
                except Exception as exc:
                    failed[index] = exc
                    logger.warning(
                        "gRPC async bulk_create failed for resource=%s index=%s: %s",
                        resource_name,
                        index,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Async bulk create completed with failures",
                succeeded=succeeded_inputs,
                failed=failed,
                operation="bulk_create",
            )
        return created

    async def bulk_update(
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:
        """
        Update multiple entities via gRPC, chunked.

        Each *item* must include the primary key field.  The default
        implementation awaits ``update()`` per item in chunks.  Adapters
        that expose a true bulk update endpoint should override this.

        On partial failure, raises :class:`GrpcBatchPartialError` with the
        failed PKs and their exceptions.
        """
        from django_admin_grpc.exceptions import GrpcBatchPartialError
        from django_admin_grpc.utils import chunked

        if not items:
            return []
        size = batch_size if batch_size is not None else self.batch_size
        pk_field = getattr(resource_class.Meta, "pk_field", "id") or "id"
        updated: list[BaseGrpcResource] = []
        succeeded_pks: list[Any] = []
        failed: dict[Any, Exception] = {}
        # Resource name is included in logs so multiple resources can be
        # disambiguated, but the raw input payload is intentionally not
        # logged — it may contain sensitive fields.
        resource_name = getattr(resource_class, "__name__", str(resource_class))
        for chunk in chunked(items, size):
            for data in chunk:
                pk = data.get(pk_field)
                if pk is None:
                    exc = ValueError(
                        f"bulk_update item missing primary key field '{pk_field}'"
                    )
                    failed[pk] = exc
                    logger.warning(
                        "gRPC async bulk_update item missing pk for resource=%s pk_field=%s",
                        resource_name,
                        pk_field,
                    )
                    continue
                try:
                    updated.append(await self.update(resource_class, str(pk), data))
                    succeeded_pks.append(pk)
                except Exception as exc:
                    failed[pk] = exc
                    logger.warning(
                        "gRPC async bulk_update failed for resource=%s pk=%s: %s",
                        resource_name,
                        pk,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Async bulk update completed with failures",
                succeeded=succeeded_pks,
                failed=failed,
                operation="bulk_update",
            )
        return updated

    async def bulk_delete(
        self,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],
        *,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """
        Delete multiple entities by primary key, chunked.

        The default implementation awaits ``delete()`` per PK in chunks. On
        partial failure, raises :class:`GrpcBatchPartialError` and includes
        the succeeded and failed PKs. On full success, returns a summary
        mapping of the form ``{"deleted": int, "failed": list[Any]}`` where
        ``failed`` is an empty list.
        """
        from django_admin_grpc.exceptions import GrpcBatchPartialError
        from django_admin_grpc.utils import chunked

        if not pks:
            return {"deleted": 0, "failed": []}
        size = batch_size if batch_size is not None else self.batch_size
        succeeded_pks: list[Any] = []
        failed: dict[Any, Exception] = {}
        # Resource name is included in logs so multiple resources can be
        # disambiguated.  ``bulk_delete`` only logs the PK (not a payload),
        # but the resource name is kept consistent with bulk_create / update.
        resource_name = getattr(resource_class, "__name__", str(resource_class))
        for chunk in chunked(pks, size):
            for pk in chunk:
                try:
                    await self.delete(resource_class, str(pk))
                    succeeded_pks.append(pk)
                except Exception as exc:
                    failed[pk] = exc
                    logger.warning(
                        "gRPC async bulk_delete failed for resource=%s pk=%s: %s",
                        resource_name,
                        pk,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Async bulk delete completed with failures",
                succeeded=succeeded_pks,
                failed=failed,
                operation="bulk_delete",
            )
        return {"deleted": len(succeeded_pks), "failed": []}

    @property
    def supports_create(self) -> bool:
        return type(self).create is not BaseAsyncGrpcServiceAdapter.create

    @property
    def supports_update(self) -> bool:
        return type(self).update is not BaseAsyncGrpcServiceAdapter.update

    @property
    def supports_delete(self) -> bool:
        return type(self).delete is not BaseAsyncGrpcServiceAdapter.delete

    async def channel(self) -> grpc.aio.Channel:
        """Return the lazily initialized async gRPC channel."""
        if self._channel is None:
            async with self._channel_lock:
                if self._channel is None:
                    raw_channel = self._create_channel(self.target)
                    self._channel = await self._wrap_channel(raw_channel)
        return self._channel

    async def get_channel(self) -> grpc.aio.Channel:
        """Alias for ``await channel()``."""
        return await self.channel()

    def _create_channel(self, target: str) -> grpc.aio.Channel:
        """Create a raw ``grpc.aio`` channel."""
        if self.credentials is not None:
            return grpc.aio.secure_channel(target, self.credentials)
        return grpc.aio.insecure_channel(target)

    async def _wrap_channel(self, channel: grpc.aio.Channel) -> grpc.aio.Channel:
        """
        Hook to wrap a raw channel.

        The default implementation returns the channel unchanged.  Subclasses
        may override to add interceptors.
        """
        return channel

    async def close(self) -> None:
        """Close the async channel if it was initialized."""
        channel = self._channel
        self._channel = None
        if channel is not None:
            try:
                await channel.close()
            except Exception:
                logger.exception("Error closing async gRPC channel for %s", self.service_name)

    @staticmethod
    def _map_rpc_error(exc: grpc.RpcError) -> Exception:
        """Map a gRPC error to a typed exception."""
        return map_grpc_error(exc)


class AsyncAdapterRegistry:
    """
    A thread-safe registry mapping service names to async adapter instances.

    The registry itself is synchronous (registration/lookup happens from sync
    Django code), but the adapters it stores expose async methods.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseAsyncGrpcServiceAdapter] = {}
        self._lock = threading.RLock()
        self._frozen = False

    def register(self, service_name: str, adapter: BaseAsyncGrpcServiceAdapter) -> None:
        """Register an async adapter under *service_name*."""
        ensure_aio_initialized()
        if self._frozen:
            raise RuntimeError("Async adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Async adapter registry is frozen")
            self._adapters[service_name] = adapter
        logger.info("Registered async gRPC adapter for service: %s", service_name)

    def unregister(self, service_name: str) -> None:
        """Remove a registered async adapter."""
        if self._frozen:
            raise RuntimeError("Async adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Async adapter registry is frozen")
            if service_name in self._adapters:
                del self._adapters[service_name]
        logger.info("Unregistered async gRPC adapter for service: %s", service_name)

    def get_adapter(self, service_name: str) -> BaseAsyncGrpcServiceAdapter | None:
        """Return the async adapter for *service_name*, or ``None``."""
        ensure_aio_initialized()
        if self._frozen:
            return self._adapters.get(service_name)
        with self._lock:
            return self._adapters.get(service_name)

    def list_services(self) -> list[str]:
        """Return all registered async service names."""
        if self._frozen:
            return list(self._adapters.keys())
        with self._lock:
            return list(self._adapters.keys())

    def clear(self) -> None:
        """Remove every async adapter. Useful in tests."""
        if self._frozen:
            raise RuntimeError("Async adapter registry is frozen")
        with self._lock:
            if self._frozen:
                raise RuntimeError("Async adapter registry is frozen")
            self._adapters.clear()

    def freeze(self) -> None:
        """Make the registry read-only."""
        with self._lock:
            self._frozen = True

    async def close_all(self) -> None:
        """Close every registered async adapter's channel."""
        if self._frozen:
            adapters = list(self._adapters.values())
        else:
            with self._lock:
                adapters = list(self._adapters.values())
        for adapter in adapters:
            try:
                await adapter.close()
            except Exception:
                logger.exception(
                    "Error closing async adapter for service: %s", adapter.service_name
                )


# Module-level singleton.
async_adapter_registry = AsyncAdapterRegistry()
