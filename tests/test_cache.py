"""
Tests for django_admin_grpc.cache module.
"""

from django.core.cache import cache as default_cache

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.cache import (
    _UNSET,
    CachedAdapterMixin,
    GrpcAdminCache,
    _stable_json,
)
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import (
    BaseGrpcResource,
    CharFieldConfig,
    IntegerFieldConfig,
)


class ItemResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "cacheitem"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class CountingAdapter(BaseGrpcServiceAdapter):
    """Tracks list/get calls for cache verification."""

    service_name = "cache_counting"

    def __init__(self):
        self.list_calls = 0
        self.get_calls = 0
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    def list(self, resource_class, page=1, page_size=25, filters=None):
        self.list_calls += 1
        return PagedResult(
            items=[resource_class(id=1, name="A")],
            total=1,
            page=page,
            page_size=page_size,
        )

    def get(self, resource_class, pk):
        self.get_calls += 1
        return resource_class(id=int(pk), name=f"item-{pk}")

    def create(self, resource_class, data):
        self.create_calls += 1
        return resource_class(**data)

    def update(self, resource_class, pk, data):
        self.update_calls += 1
        # Pop the PK from the payload so we don't double-supply it as a
        # keyword argument when constructing the resource.
        payload = {k: v for k, v in data.items() if k != "id"}
        return resource_class(id=pk, **payload)

    def delete(self, resource_class, pk):
        self.delete_calls += 1
        return True


class CachedAdapter(CachedAdapterMixin, CountingAdapter):
    pass


class TestStableJson:
    def test_dict_order_insensitive(self):
        assert _stable_json({"b": 1, "a": 2}) == _stable_json({"a": 2, "b": 1})

    def test_nested_dict_order_insensitive(self):
        a = _stable_json({"outer": {"b": 1, "a": 2}})
        b = _stable_json({"outer": {"a": 2, "b": 1}})
        assert a == b

    def test_handles_non_json_values(self):
        # ``default=str`` keeps the call non-throwing for odd values.
        result = _stable_json({"when": "2024-01-01"})
        assert "2024-01-01" in result


class TestGrpcAdminCache:
    def test_disabled_by_default_returns_none(self):
        c = GrpcAdminCache()
        c.set("k", "v")
        assert c.get("k") is None

    def test_make_key_includes_resource_and_operation(self):
        c = GrpcAdminCache()
        key = c.make_key(ItemResource, "list", {"page": 1, "filters": {}})
        # ``ItemResource`` is the namespaced resource qualifier; we look for
        # a case-insensitive substring to keep this stable if Python emits
        # a different module name.
        assert "itemresource" in key.lower()
        assert ":list:" in key

    def test_make_key_order_insensitive(self):
        c = GrpcAdminCache()
        k1 = c.make_key(ItemResource, "get", {"pk": 1, "extra": "x"})
        k2 = c.make_key(ItemResource, "get", {"extra": "x", "pk": 1})
        assert k1 == k2

    def test_from_settings_disabled(self, settings):
        settings.GRPC_ADMIN_CACHE_ENABLED = False
        c = GrpcAdminCache.from_settings()
        assert c.enabled is False

    def test_from_settings_enabled(self, settings):
        settings.GRPC_ADMIN_CACHE_ENABLED = True
        settings.GRPC_ADMIN_CACHE_TTL = 120
        settings.GRPC_ADMIN_CACHE_PREFIX = "myapp"
        settings.GRPC_ADMIN_CACHE_BACKEND = "default"
        c = GrpcAdminCache.from_settings()
        assert c.enabled is True
        assert c.ttl == 120
        assert c.prefix == "myapp"

    def test_enabled_get_set(self):
        default_cache.clear()
        c = GrpcAdminCache(prefix="cache_test", ttl=10, enabled=True)
        c.set("k", "v")
        assert c.get("k") == "v"
        c.delete("k")
        assert c.get("k") is None
        default_cache.clear()

    def test_invalid_backend_falls_back_to_disabled(self):
        c = GrpcAdminCache(backend="nonexistent-backend-xyz", enabled=True)
        # Should disable gracefully.
        assert c.enabled is False
        assert c.get("anything") is None

    def test_delete_many(self):
        default_cache.clear()
        c = GrpcAdminCache(prefix="cache_test_many", ttl=10, enabled=True)
        c.set("a", 1)
        c.set("b", 2)
        c.delete_many(["a", "b", "missing"])
        assert c.get("a") is None
        assert c.get("b") is None
        default_cache.clear()


class TestCachedAdapterMixin:
    def test_disabled_cache_is_pass_through(self):
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(enabled=False)

        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2

    def test_enabled_cache_hits_on_second_call(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_adapter", ttl=10, enabled=True)

        result1 = adapter.list(ItemResource, page=1, page_size=25)
        result2 = adapter.list(ItemResource, page=1, page_size=25)
        # Only one upstream call; the second is served from cache.
        assert adapter.list_calls == 1
        # The second result is a fresh deserialised copy from the cache
        # backend; assert structural fields, not identity.
        assert len(result1.items) == len(result2.items) == 1
        assert result1.items[0].id == result2.items[0].id == 1
        assert result1.items[0].name == result2.items[0].name
        assert result1.total == result2.total
        default_cache.clear()

    def test_create_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv", ttl=10, enabled=True)

        adapter.list(ItemResource, page=1, page_size=25)  # cached
        adapter.list(ItemResource, page=1, page_size=25)  # cache hit
        assert adapter.list_calls == 1

        adapter.create(ItemResource, {"id": 99, "name": "X"})

        # Cache should be busted — next call hits the adapter again.
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_update_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv2", ttl=10, enabled=True)
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 1

        adapter.update(ItemResource, 1, {"name": "Y"})

        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_delete_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv3", ttl=10, enabled=True)
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 1

        adapter.delete(ItemResource, "1")
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_bulk_create_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv4", ttl=10, enabled=True)
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 1

        adapter.bulk_create(ItemResource, [{"id": 1, "name": "x"}])
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_bulk_update_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv5", ttl=10, enabled=True)
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 1

        # Don't include the PK in the update payload — CountingAdapter.update
        # constructs the resource via ``resource_class(id=pk, **data)`` and
        # would fail on a duplicate ``id`` keyword.
        adapter.bulk_update(ItemResource, [{"id": 1, "name": "x"}])
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_bulk_delete_invalidates_cache(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_inv6", ttl=10, enabled=True)
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 1

        adapter.bulk_delete(ItemResource, ["1"])
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        default_cache.clear()

    def test_get_caches_result(self):
        default_cache.clear()
        adapter = CachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_get", ttl=10, enabled=True)
        r1 = adapter.get(ItemResource, "1")
        r2 = adapter.get(ItemResource, "1")
        # The cache backend deserialises on read, so we compare fields
        # rather than identity.
        assert r1.id == r2.id == 1
        assert r1.name == r2.name
        assert adapter.get_calls == 1
        default_cache.clear()

    def test_get_caches_not_found(self):
        default_cache.clear()

        class NoneAdapter(BaseGrpcServiceAdapter):
            """Adapter that always returns ``None`` from ``get``."""

            service_name = "none_adapter"

            def __init__(self):
                self.get_calls = 0

            def list(self, resource_class, page=1, page_size=25, filters=None):
                return PagedResult(items=[])

            def get(self, resource_class, pk):
                self.get_calls += 1
                return None

        class NoneCachedAdapter(CachedAdapterMixin, NoneAdapter):
            pass

        adapter = NoneCachedAdapter()
        adapter.grpc_cache = GrpcAdminCache(prefix="cache_get_none", ttl=10, enabled=True)
        r1 = adapter.get(ItemResource, "1")
        r2 = adapter.get(ItemResource, "1")
        assert r1 is None
        assert r2 is None
        # Second call should still be cached, even though the value is None.
        assert adapter.get_calls == 1
        default_cache.clear()

    def test_ensure_cache_initialises_from_settings(self, settings):
        settings.GRPC_ADMIN_CACHE_ENABLED = True
        settings.GRPC_ADMIN_CACHE_PREFIX = "lazy_init"
        settings.GRPC_ADMIN_CACHE_TTL = 30
        settings.GRPC_ADMIN_CACHE_BACKEND = "default"

        adapter = CachedAdapter()
        # ``grpc_cache`` is unset on both the class and the instance —
        # this is the new "use global settings" sentinel, NOT an explicit
        # opt-out.
        assert getattr(adapter, "grpc_cache", _UNSET) is _UNSET
        # First call lazy-loads.
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.grpc_cache is not None
        assert adapter.grpc_cache.enabled is True
        default_cache.clear()

    def test_cache_none_passes_through(self):
        adapter = CachedAdapter()
        adapter.grpc_cache = None
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2

    def test_explicit_none_opt_out_overrides_global_cache_enabled(self, settings):
        """Regression: ``grpc_cache = None`` must be honoured even when
        ``GRPC_ADMIN_CACHE_ENABLED`` is ``True``.

        Previously ``_ensure_cache`` treated ``None`` as "uninitialised"
        and rebuilt a cache from the global settings, silently caching
        even when an adapter had explicitly opted out.
        """
        # Global cache is enabled and uses the live Django cache backend.
        settings.GRPC_ADMIN_CACHE_ENABLED = True
        settings.GRPC_ADMIN_CACHE_PREFIX = "opt_out_regression"
        settings.GRPC_ADMIN_CACHE_TTL = 60
        settings.GRPC_ADMIN_CACHE_BACKEND = "default"
        default_cache.clear()

        adapter = CachedAdapter()
        # Per-adapter explicit opt-out — documented API.
        adapter.grpc_cache = None

        # list() must hit upstream both times; no cache hit.
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2

        # get() must hit upstream both times; no cache hit.
        adapter.get(ItemResource, "1")
        adapter.get(ItemResource, "1")
        assert adapter.get_calls == 2

        # The opt-out must not be overwritten by lazy build-from-settings.
        assert adapter.grpc_cache is None

        # Verify the global cache backend was not touched.
        assert len(default_cache._cache.keys()) == 0  # type: ignore[attr-defined]
        default_cache.clear()

    def test_class_level_none_opt_out_overrides_global_cache_enabled(self, settings):
        """Class-level ``grpc_cache = None`` must be honoured globally."""
        settings.GRPC_ADMIN_CACHE_ENABLED = True
        settings.GRPC_ADMIN_CACHE_PREFIX = "opt_out_class_regression"
        settings.GRPC_ADMIN_CACHE_TTL = 60
        settings.GRPC_ADMIN_CACHE_BACKEND = "default"
        default_cache.clear()

        class ClassLevelOptOutAdapter(CachedAdapterMixin, CountingAdapter):
            grpc_cache = None  # class-level opt-out

        adapter = ClassLevelOptOutAdapter()
        adapter.list(ItemResource, page=1, page_size=25)
        adapter.list(ItemResource, page=1, page_size=25)
        assert adapter.list_calls == 2
        assert adapter.grpc_cache is None
        default_cache.clear()

    def test_unset_vs_explicit_none_distinction(self):
        """Verify the sentinel correctly distinguishes unset from None.

        Without this distinction the mixin would always lazy-load from
        settings and the per-adapter opt-out would be unreachable.
        """
        # Unset: no class- or instance-level attribute.
        adapter = CachedAdapter()
        assert getattr(adapter, "grpc_cache", _UNSET) is _UNSET

        # Explicit None: instance-level opt-out.
        adapter_opt_out = CachedAdapter()
        adapter_opt_out.grpc_cache = None
        assert getattr(adapter_opt_out, "grpc_cache", _UNSET) is None

        # Explicit instance: use as-is.
        cache = GrpcAdminCache(prefix="explicit", ttl=10, enabled=False)
        adapter_explicit = CachedAdapter()
        adapter_explicit.grpc_cache = cache
        assert getattr(adapter_explicit, "grpc_cache", _UNSET) is cache
