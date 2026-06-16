"""
Optional read-through cache for gRPC admin adapters.

The package ships two pieces:

* :class:`GrpcAdminCache` — a thin wrapper over the Django cache framework
  that builds stable, namespaced keys for resource + operation + kwargs.
* :class:`CachedAdapterMixin` — a mixin that augments
  :class:`~django_admin_grpc.adapters.BaseGrpcServiceAdapter` with cache reads
  for ``list`` / ``get`` and cache invalidation for ``create`` / ``update`` /
  ``delete`` (and the matching ``bulk_*`` helpers).

The mixin is fully opt-in: if the mixin is **not** in the adapter's MRO, or if
``grpc_cache`` is ``None`` (or the package is disabled globally), the methods
behave exactly like the base adapter.

Configuration (read once on first use, no Django settings restart required)::

    GRPC_ADMIN = {
        "CACHE_ENABLED": True,        # default False
        "CACHE_TTL": 60,              # seconds
        "CACHE_PREFIX": "grpc_admin", # key prefix
        "CACHE_BACKEND": "default",   # Django CACHES alias
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, TypeVar, cast

from django.core.cache import caches

from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import BaseGrpcResource
from django_admin_grpc.settings import get_setting

logger = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["GrpcAdminCache", "CachedAdapterMixin"]


# Sentinel used to distinguish an adapter that has not declared
# ``grpc_cache`` (default — lazy-load from settings) from one that
# has explicitly set ``grpc_cache = None`` (per-adapter opt-out).
# Any instance of this object is unique and must not be reused.
_UNSET: Any = object()


def _stable_json(data: Any) -> str:
    """Return a stable JSON encoding of *data* for use in cache keys.

    Args:
        data: Any JSON-serializable value.

    Returns:
        A deterministic JSON string.
    """
    return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))


class GrpcAdminCache:
    """
    Thin wrapper around the Django cache framework for gRPC admin adapters.

    A cache key is composed as ``{prefix}:{resource}:{operation}:{sha256(args)}``
    where ``args`` is a JSON encoding of the keyword arguments sorted by key.
    The hashing is deliberately order-insensitive: callers may pass a dict
    in any order and still hit the same cached value.

    Args:
        prefix: Key namespace (typically ``GRPC_ADMIN_CACHE_PREFIX``).
        ttl: Default TTL in seconds.
        backend: Django ``CACHES`` alias to use; defaults to ``"default"``.
        enabled: When ``False``, :meth:`get` always returns ``None`` and
            :meth:`set` is a no-op.  When ``True``, the Django cache is used.
    """

    def __init__(
        self,
        *,
        prefix: str = "grpc_admin",
        ttl: int = 60,
        backend: str = "default",
        enabled: bool = False,
    ) -> None:
        self.prefix = prefix
        self.ttl = ttl
        self.backend = backend
        self.enabled = enabled
        self._cache: Any = None
        if self.enabled:
            try:
                self._cache = caches[backend]
            except Exception:
                logger.exception(
                    "Failed to resolve Django cache backend %r; falling back to no-op",
                    backend,
                )
                self.enabled = False
                self._cache = None

    @classmethod
    def from_settings(cls) -> GrpcAdminCache:
        """Build a cache from the active Django settings.

        Reads ``GRPC_ADMIN_CACHE_*`` keys; falls back to safe defaults.
        """
        try:
            enabled = bool(get_setting("GRPC_ADMIN_CACHE_ENABLED"))
        except Exception:
            enabled = False
        try:
            ttl = int(get_setting("GRPC_ADMIN_CACHE_TTL") or 60)
        except Exception:
            ttl = 60
        try:
            prefix = str(get_setting("GRPC_ADMIN_CACHE_PREFIX") or "grpc_admin")
        except Exception:
            prefix = "grpc_admin"
        try:
            backend = str(get_setting("GRPC_ADMIN_CACHE_BACKEND") or "default")
        except Exception:
            backend = "default"
        return cls(
            prefix=prefix,
            ttl=ttl,
            backend=backend,
            enabled=enabled,
        )

    # ── Key construction ──────────────────────────────────────────────────

    def make_key(
        self,
        resource: type | str,
        operation: str,
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        """
        Build a stable cache key.

        Args:
            resource: Resource class (or its dotted name) for namespacing.
            operation: Adapter method name (``"list"``, ``"get"``,
                ``"bulk_create"`` ...).
            kwargs: Keyword arguments to the operation.  Order-insensitive.

        Returns:
            A string cache key.
        """
        if isinstance(resource, type):
            resource_name = f"{resource.__module__}.{resource.__qualname__}"
        else:
            resource_name = str(resource)
        normalized = kwargs or {}
        body = _stable_json(normalized)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return f"{self.prefix}:{resource_name}:{operation}:{digest}"

    # ── Backend accessors ─────────────────────────────────────────────────

    def get(self, key: str) -> Any:
        """
        Return the cached value for *key* or ``None``.

        When caching is disabled, always returns ``None``.
        """
        if not self.enabled or self._cache is None:
            return None
        try:
            return self._cache.get(key)
        except Exception:
            logger.exception("Cache get failed for key=%s", key)
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Store *value* under *key*.

        No-op when caching is disabled.
        """
        if not self.enabled or self._cache is None:
            return
        try:
            self._cache.set(key, value, ttl if ttl is not None else self.ttl)
        except Exception:
            logger.exception("Cache set failed for key=%s", key)

    def delete(self, key: str) -> None:
        """
        Remove *key* from the cache.

        No-op when caching is disabled.
        """
        if not self.enabled or self._cache is None:
            return
        try:
            self._cache.delete(key)
        except Exception:
            logger.exception("Cache delete failed for key=%s", key)

    def delete_many(self, keys: list[str]) -> None:
        """
        Remove every key in *keys* from the cache.

        No-op when caching is disabled.
        """
        if not self.enabled or self._cache is None or not keys:
            return
        try:
            self._cache.delete_many(keys)
        except Exception:
            logger.exception("Cache delete_many failed (%d keys)", len(keys))


class CachedAdapterMixin:
    """
    Mixin that adds read-through caching and write-through invalidation to a
    :class:`~django_admin_grpc.adapters.BaseGrpcServiceAdapter` subclass.

    The mixin **does not** call ``super().__init__()`` explicitly; it is
    designed to be combined with the standard adapter class via multiple
    inheritance, e.g.::

        class CachedAdapter(CachedAdapterMixin, BaseGrpcServiceAdapter):
            ...

    Behaviour:

    * ``list()`` and ``get()`` are intercepted to populate / consult
      ``self.grpc_cache``.
    * ``create()``, ``update()``, ``delete()`` and the ``bulk_*`` helpers
      invalidate any cached list / get entries for the affected resource.
    * When ``grpc_cache`` is not declared on the class or instance, the
      mixin lazy-loads a :class:`GrpcAdminCache` from the active Django
      settings on first use (so ``GRPC_ADMIN_CACHE_ENABLED`` and friends
      take effect automatically).
    * When ``grpc_cache`` is set to ``None`` (on the class or instance),
      caching is disabled for that adapter and every method falls through
      to the base implementation unchanged.  This is the documented
      per-adapter opt-out — it is honoured even when the global cache is
      enabled.
    * When ``grpc_cache`` is a :class:`GrpcAdminCache` instance, that
      instance is used directly.
    """

    #: Optional cache instance.  Leave unset to use the global Django
    #: settings; set to ``None`` to opt out of caching for this adapter;
    #: set to a :class:`GrpcAdminCache` instance for full control.
    grpc_cache: GrpcAdminCache | None

    def _ensure_cache(self) -> GrpcAdminCache | None:
        """Lazily resolve the cache for this adapter.

        Distinguishes three states for the ``grpc_cache`` attribute:

        * **Unset** (no class- or instance-level declaration) — build
          a :class:`GrpcAdminCache` from Django settings and cache it
          on the instance.
        * **Explicitly** ``None`` — honour the per-adapter opt-out and
          return ``None`` so the read methods pass through to the base
          adapter.
        * **A** :class:`GrpcAdminCache` **instance** — return it as-is.
        """
        cache = getattr(self, "grpc_cache", _UNSET)
        if cache is _UNSET:
            try:
                cache = GrpcAdminCache.from_settings()
            except Exception:
                logger.exception("Failed to build GrpcAdminCache from settings")
                cache = GrpcAdminCache(enabled=False)
            self.grpc_cache = cache
            return cache
        # Either an explicit ``None`` (opt-out) or a GrpcAdminCache instance.
        return cast(GrpcAdminCache | None, cache)

    # ── Invalidation helpers ──────────────────────────────────────────────

    def _invalidate_resource(
        self,
        resource_class: type[BaseGrpcResource],
    ) -> None:
        """Invalidate all list/get entries for *resource_class*."""
        cache = getattr(self, "grpc_cache", None)
        if cache is None:
            return
        prefix = cache.prefix
        resource_name = f"{resource_class.__module__}.{resource_class.__qualname__}"
        # We don't know the exact list of cached keys, so we delete by a
        # versioned namespace: bumping the resource version makes every prior
        # list/get key unreachable. The version is stored under
        # ``{prefix}:{resource}:_v``.
        version_key = f"{prefix}:{resource_name}:_v"
        try:
            backend = cache._cache
            if backend is None:
                return
            try:
                current = backend.get(version_key) or 0
            except Exception:
                current = 0
            backend.set(version_key, current + 1, cache.ttl)
        except Exception:
            logger.exception("Cache invalidation failed for %s", resource_name)

    def _versioned_key(
        self,
        cache: GrpcAdminCache,
        resource: type | str,
        operation: str,
        kwargs: dict[str, Any],
    ) -> str:
        """Build a cache key that includes the current resource version."""
        base = cache.make_key(resource, operation, kwargs)
        if isinstance(resource, type):
            resource_name = f"{resource.__module__}.{resource.__qualname__}"
        else:
            resource_name = str(resource)
        version_key = f"{cache.prefix}:{resource_name}:_v"
        version = 0
        backend = cache._cache
        if backend is not None:
            try:
                version = backend.get(version_key) or 0
            except Exception:
                version = 0
        return f"v{version}:" + base

    # ── Cached read paths ─────────────────────────────────────────────────

    def list(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> PagedResult:
        cache = self._ensure_cache()
        upstream = cast(Any, super())
        if cache is None or not cache.enabled:
            return cast(
                PagedResult,
                upstream.list(
                    resource_class,
                    page=page,
                    page_size=page_size,
                    filters=filters,
                ),
            )
        key = self._versioned_key(
            cache,
            resource_class,
            "list",
            {"page": page, "page_size": page_size, "filters": filters or {}},
        )
        cached = cache.get(key)
        if cached is not None:
            return cast(PagedResult, cached)
        result = upstream.list(
            resource_class,
            page=page,
            page_size=page_size,
            filters=filters,
        )
        cache.set(key, result)
        return cast(PagedResult, result)

    def get(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> BaseGrpcResource | None:
        cache = self._ensure_cache()
        upstream = cast(Any, super())
        if cache is None or not cache.enabled:
            return cast(
                BaseGrpcResource | None,
                upstream.get(resource_class, pk),
            )
        key = self._versioned_key(cache, resource_class, "get", {"pk": pk})
        cached = cache.get(key)
        if cached is not None:
            # Sentinel string marks a cached "not found" result so we can
            # distinguish it from a real missing cache entry.  We use a
            # string (rather than a module-level singleton) because Django
            # cache backends deserialise on read and a pickled singleton
            # would no longer compare equal to the original.
            if cached == _CACHE_MISS_SENTINEL:
                return None
            return cast(BaseGrpcResource, cached)
        result = upstream.get(resource_class, pk)
        cache.set(
            key,
            result if result is not None else _CACHE_MISS_SENTINEL,
        )
        return cast(BaseGrpcResource | None, result)

    # ── Write paths: invalidate, then delegate ───────────────────────────

    def create(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        self._invalidate_resource(resource_class)
        return cast(
            BaseGrpcResource,
            cast(Any, super()).create(resource_class, data),
        )

    def update(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
        data: dict[str, Any],
    ) -> BaseGrpcResource:
        self._invalidate_resource(resource_class)
        return cast(
            BaseGrpcResource,
            cast(Any, super()).update(resource_class, pk, data),
        )

    def delete(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        pk: str,
    ) -> bool:
        self._invalidate_resource(resource_class)
        return cast(bool, cast(Any, super()).delete(resource_class, pk))

    def bulk_create(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],  # type: ignore[valid-type]
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:  # type: ignore[valid-type]
        self._invalidate_resource(resource_class)
        return cast(
            list[BaseGrpcResource],  # type: ignore[valid-type]
            cast(Any, super()).bulk_create(resource_class, items, batch_size=batch_size),
        )

    def bulk_update(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        items: list[dict[str, Any]],  # type: ignore[valid-type]
        *,
        batch_size: int | None = None,
    ) -> list[BaseGrpcResource]:  # type: ignore[valid-type]
        self._invalidate_resource(resource_class)
        return cast(
            list[BaseGrpcResource],  # type: ignore[valid-type]
            cast(Any, super()).bulk_update(resource_class, items, batch_size=batch_size),
        )

    def bulk_delete(  # type: ignore[override]
        self,
        resource_class: type[BaseGrpcResource],
        pks: list[Any],  # type: ignore[valid-type]
        *,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        self._invalidate_resource(resource_class)
        return cast(
            dict[str, Any],
            cast(Any, super()).bulk_delete(resource_class, pks, batch_size=batch_size),
        )


# Sentinel string stored in the cache so a real ``get() == None`` (not
# found) can be distinguished from "no entry present yet".  The string is
# safe across pickle / JSON / memcache serialisation.
_CACHE_MISS_SENTINEL = "__grpc_admin_cache_miss__"
