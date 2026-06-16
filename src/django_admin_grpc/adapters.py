"""
Base gRPC service adapter interface.

Concrete adapters subclass ``BaseGrpcServiceAdapter`` and implement ``list()``,
``get()`` and optionally ``create()``, ``update()``, ``delete()``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import grpc

from django_admin_grpc.exceptions import GrpcBatchPartialError, map_grpc_error
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.utils import chunked

if TYPE_CHECKING:
    from django_admin_grpc.pool import GrpcChannelPool
    from django_admin_grpc.resources import BaseGrpcResource

logger = logging.getLogger(__name__)


class BaseGrpcServiceAdapter(ABC):
    """
    Abstract interface between Django admin and a remote gRPC service.

    Attributes:
        service_name: Human-readable name used by the registry.
        grpc_pool: Optional ``GrpcChannelPool`` used to acquire channels. When
            set, ``get_channel`` borrows channels from the pool instead of using
            the legacy ``self.channel`` property.
        batch_size: Default chunk size used by fallback ``bulk_*`` methods
            when callers do not specify a size. Defaults to ``100``.
    """

    service_name: str = ""
    grpc_pool: GrpcChannelPool | None = None
    batch_size: int = 100

    @contextmanager
    def get_channel(self) -> Any:
        """
        Context manager that yields a usable gRPC channel.

        If ``grpc_pool`` is configured, a channel is borrowed from the pool and
        returned on exit.  Otherwise the legacy ``self.channel`` attribute is
        yielded, preserving backward compatibility for adapters that build and
        manage their own channel.

        Adapters written before the pool feature can continue to use
        ``self.channel`` directly without any change.
        """
        if self.grpc_pool is not None:
            with self.grpc_pool.get_channel() as channel:
                yield channel
        else:
            yield self.channel  # type: ignore[attr-defined]

    @abstractmethod
    def list(
        self,
        resource_class: type[BaseGrpcResource],
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> PagedResult:
        """
        Fetch a page of entities.

        Args:
            resource_class: The resource class to instantiate for each row.
            page: 1-indexed page number.
            page_size: Items per page.
            filters: Optional query/filter dictionary.

        Returns:
            A ``PagedResult`` containing items and pagination metadata.
        """
        ...

    @abstractmethod
    def get(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> BaseGrpcResource | None:
        """
        Fetch a single entity by primary key.

        Args:
            resource_class: The resource class to instantiate.
            pk: Primary key value.

        Returns:
            A resource instance, or ``None`` if not found.
        """
        ...

    def batch_get(
        self,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],  # type: ignore[valid-type]
    ) -> dict[Any, BaseGrpcResource | None]:
        """
        Fetch multiple entities by primary key in a batch.

        The default implementation loops ``get()`` one PK at a time. Concrete
        adapters should override this when the backing service supports a true
        batch lookup.

        Args:
            resource_class: The resource class to instantiate.
            pks: Primary key values to fetch.

        Returns:
            A mapping of PK to resource instance (or ``None`` if not found).
        """
        result: dict[Any, BaseGrpcResource | None] = {}
        for pk in pks:  # type: ignore[attr-defined]
            result[pk] = self.get(resource_class, str(pk))
        return result

    def create(
        self,
        resource_class: type[BaseGrpcResource],
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Create a new entity via gRPC."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support create")

    def update(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        """Update an existing entity via gRPC."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support update")

    def delete(
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> bool:
        """Delete an entity via gRPC."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support delete")

    # ── Bulk operations (chunked fallback) ────────────────────────────────

    def bulk_create(
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:
        """
        Create multiple entities via gRPC, chunked.

        The default implementation iterates the configured ``create()`` method
        in chunks of ``batch_size`` (defaulting to ``self.batch_size``).
        Adapters that expose a true bulk create endpoint should override this.

        On partial failure the method raises
        :class:`GrpcBatchPartialError` so the caller can react to the failed
        subset. Each failed item is mapped to the underlying exception.

        Args:
            resource_class: Resource class to instantiate for created items.
            items: List of dictionaries, one per entity to create.
            batch_size: Optional chunk size override.

        Returns:
            A list of created resources (one per successfully created item,
            in chunk-then-item order).
        """
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
                    created.append(self.create(resource_class, data))
                    succeeded_inputs.append(data)
                except Exception as exc:
                    failed[index] = exc
                    logger.warning(
                        "gRPC bulk_create failed for resource=%s index=%s: %s",
                        resource_name,
                        index,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Bulk create completed with failures",
                succeeded=succeeded_inputs,
                failed=failed,
                operation="bulk_create",
            )
        return created

    def bulk_update(
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:
        """
        Update multiple entities via gRPC, chunked.

        Each *item* must include the primary key field.  The PK name is
        discovered from the resource ``Meta.pk_field`` (defaulting to
        ``"id"``).  The default implementation calls ``update()`` per item in
        chunks; concrete adapters can override when a true bulk update exists.

        On partial failure the method raises
        :class:`GrpcBatchPartialError` with the failed PKs and their
        exceptions.

        Args:
            resource_class: Resource class describing the entity shape.
            items: List of dictionaries, each including the PK field plus
                the fields to update.
            batch_size: Optional chunk size override.

        Returns:
            A list of updated resources (one per successful update, in
            chunk-then-item order).
        """
        if not items:
            return []
        size = batch_size if batch_size is not None else self.batch_size
        pk_field = self._get_pk_field_name(resource_class)
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
                    exc = ValueError(f"bulk_update item missing primary key field '{pk_field}'")
                    failed[pk] = exc
                    logger.warning(
                        "gRPC bulk_update item missing pk for resource=%s pk_field=%s",
                        resource_name,
                        pk_field,
                    )
                    continue
                try:
                    updated.append(self.update(resource_class, str(pk), data))
                    succeeded_pks.append(pk)
                except Exception as exc:
                    failed[pk] = exc
                    logger.warning(
                        "gRPC bulk_update failed for resource=%s pk=%s: %s",
                        resource_name,
                        pk,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Bulk update completed with failures",
                succeeded=succeeded_pks,
                failed=failed,
                operation="bulk_update",
            )
        return updated

    def bulk_delete(
        self,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],
        *,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """
        Delete multiple entities by primary key, chunked.

        The default implementation calls ``delete()`` per PK in chunks. On
        partial failure, raises :class:`GrpcBatchPartialError` and includes
        the succeeded and failed PKs. On full success, returns a summary
        mapping of the form ``{"deleted": int, "failed": list[Any]}`` where
        ``failed`` is an empty list.

        Args:
            resource_class: Resource class describing the entity shape.
            pks: List of primary key values to delete.
            batch_size: Optional chunk size override.

        Returns:
            ``{"deleted": <int>, "failed": [<pk>, ...]}`` on full success.

        Raises:
            GrpcBatchPartialError: When one or more deletes fail.
        """
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
                    self.delete(resource_class, str(pk))
                    succeeded_pks.append(pk)
                except Exception as exc:
                    failed[pk] = exc
                    logger.warning(
                        "gRPC bulk_delete failed for resource=%s pk=%s: %s",
                        resource_name,
                        pk,
                        exc,
                    )
        if failed:
            raise GrpcBatchPartialError(
                "Bulk delete completed with failures",
                succeeded=succeeded_pks,
                failed=failed,
                operation="bulk_delete",
            )
        return {"deleted": len(succeeded_pks), "failed": []}

    @staticmethod
    def _get_pk_field_name(
        resource_class: type[BaseGrpcResource],
    ) -> str:
        """Return the primary key field name for *resource_class*."""
        return getattr(resource_class.Meta, "pk_field", "id") or "id"

    @property
    def supports_create(self) -> bool:
        return type(self).create is not BaseGrpcServiceAdapter.create

    @property
    def supports_update(self) -> bool:
        return type(self).update is not BaseGrpcServiceAdapter.update

    @property
    def supports_delete(self) -> bool:
        return type(self).delete is not BaseGrpcServiceAdapter.delete

    def close(self) -> None:
        """Release any held connections."""
        channel = getattr(self, "_channel", None)
        if channel is not None:
            try:
                channel.close()
            except Exception:
                logger.exception("Error closing gRPC channel for %s", self.service_name)

    def _create_channel(self, target: str, **kwargs: Any) -> grpc.Channel:
        """
        Create a raw gRPC channel for *target* and wrap it with the trace interceptor.

        If wrapping raises, the raw channel is closed to avoid leaking the
        underlying connection.

        Args:
            target: gRPC target string (e.g. ``"service:50051"``).
            **kwargs: Extra arguments forwarded to ``grpc.insecure_channel``.

        Returns:
            A wrapped gRPC channel.
        """
        raw_channel = grpc.insecure_channel(target, **kwargs)
        try:
            return self._wrap_channel(raw_channel)
        except Exception:
            raw_channel.close()
            raise

    def _wrap_channel(self, channel: grpc.Channel) -> grpc.Channel:
        """
        Wrap a raw gRPC channel with the trace interceptor.

        Must be called **inside** the ``if self._channel is None:`` guard in
        concrete adapters so the channel is not double-wrapped.
        """
        from django_admin_grpc.interceptors import TraceClientInterceptor

        provider = self._trace_context_provider()
        return grpc.intercept_channel(
            channel, TraceClientInterceptor(trace_context_provider=provider)
        )

    def _trace_context_provider(self) -> Callable[[], dict[str, str]]:
        """Return the configured trace-context callable, or a no-op."""
        from django_admin_grpc.settings import get_setting

        provider = get_setting("GRPC_ADMIN_TRACE_CONTEXT_PROVIDER")
        if provider is None:
            return lambda: {}
        if callable(provider):
            return cast(Callable[[], dict[str, str]], provider)
        # Django-style dotted path
        from django.utils.module_loading import import_string

        return cast(Callable[[], dict[str, str]], import_string(provider))

    @staticmethod
    def _map_rpc_error(exc: grpc.RpcError) -> Exception:
        """Map a gRPC error to a typed exception.  Callers should ``raise`` the result."""
        return map_grpc_error(exc)
