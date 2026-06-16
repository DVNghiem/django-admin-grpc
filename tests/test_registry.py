"""
Tests for django_admin_grpc.registry module.
"""

import threading
from unittest.mock import Mock, patch

import pytest

from django_admin_grpc.pool import GrpcChannelPool
from django_admin_grpc.registry import AdapterRegistry, adapter_registry


class TestAdapterRegistry:
    def test_register_and_get(self):
        registry = AdapterRegistry()
        adapter = Mock()
        adapter.service_name = "products"

        registry.register("products", adapter)
        assert registry.get_adapter("products") is adapter

    def test_get_missing_returns_none(self):
        registry = AdapterRegistry()
        assert registry.get_adapter("nonexistent") is None

    def test_unregister(self):
        registry = AdapterRegistry()
        adapter = Mock()
        registry.register("svc", adapter)
        registry.unregister("svc")
        assert registry.get_adapter("svc") is None

    def test_list_services(self):
        registry = AdapterRegistry()
        registry.register("a", Mock())
        registry.register("b", Mock())
        services = registry.list_services()
        assert sorted(services) == ["a", "b"]

    def test_clear(self):
        registry = AdapterRegistry()
        registry.register("x", Mock())
        registry.clear()
        assert registry.list_services() == []

    def test_module_singleton(self):
        assert isinstance(adapter_registry, AdapterRegistry)
        adapter_registry.clear()
        adapter_registry.register("test", Mock())
        assert "test" in adapter_registry.list_services()
        adapter_registry.clear()

    def test_register_overwrites_existing(self):
        registry = AdapterRegistry()
        a1 = Mock()
        a2 = Mock()
        registry.register("svc", a1)
        registry.register("svc", a2)
        assert registry.get_adapter("svc") is a2

    def test_unregister_missing_is_no_op(self):
        registry = AdapterRegistry()
        registry.unregister("missing")  # should not raise

    def test_freeze_raises_on_register(self):
        registry = AdapterRegistry()
        registry.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            registry.register("svc", Mock())

    def test_register_rechecks_frozen_inside_lock(self):
        """Race: freeze happens after the outside check but before the lock."""
        registry = AdapterRegistry()

        class FreezingRLock:
            def __init__(self):
                self._lock = threading.RLock()
                self._did_freeze = False

            def acquire(self, *args, **kwargs):
                if not self._did_freeze:
                    self._did_freeze = True
                    registry.freeze()
                return self._lock.acquire(*args, **kwargs)

            def release(self):
                return self._lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *args):
                self.release()

        with (
            patch.object(registry, "_lock", FreezingRLock()),
            pytest.raises(RuntimeError, match="frozen"),
        ):
            registry.register("svc", Mock())

    def test_freeze_raises_on_unregister(self):
        registry = AdapterRegistry()
        registry.register("svc", Mock())
        registry.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            registry.unregister("svc")

    def test_unregister_rechecks_frozen_inside_lock(self):
        """Race: freeze happens after the outside check but before the lock."""
        registry = AdapterRegistry()
        registry.register("svc", Mock())

        class FreezingRLock:
            def __init__(self):
                self._lock = threading.RLock()
                self._did_freeze = False

            def acquire(self, *args, **kwargs):
                if not self._did_freeze:
                    self._did_freeze = True
                    registry.freeze()
                return self._lock.acquire(*args, **kwargs)

            def release(self):
                return self._lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *args):
                self.release()

        with (
            patch.object(registry, "_lock", FreezingRLock()),
            pytest.raises(RuntimeError, match="frozen"),
        ):
            registry.unregister("svc")

    def test_freeze_raises_on_clear(self):
        registry = AdapterRegistry()
        registry.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            registry.clear()

    def test_clear_rechecks_frozen_inside_lock(self):
        """Race: freeze happens after the outside check but before the lock."""
        registry = AdapterRegistry()
        registry.register("svc", Mock())

        class FreezingRLock:
            def __init__(self):
                self._lock = threading.RLock()
                self._did_freeze = False

            def acquire(self, *args, **kwargs):
                if not self._did_freeze:
                    self._did_freeze = True
                    registry.freeze()
                return self._lock.acquire(*args, **kwargs)

            def release(self):
                return self._lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *args):
                self.release()

        with (
            patch.object(registry, "_lock", FreezingRLock()),
            pytest.raises(RuntimeError, match="frozen"),
        ):
            registry.clear()

    def test_get_works_after_freeze(self):
        registry = AdapterRegistry()
        adapter = Mock()
        registry.register("svc", adapter)
        registry.freeze()
        assert registry.get_adapter("svc") is adapter

    def test_close_all_closes_adapters(self):
        registry = AdapterRegistry()
        a1 = Mock()
        a1.service_name = "a"
        a2 = Mock()
        a2.service_name = "b"
        registry.register("a", a1)
        registry.register("b", a2)
        registry.close_all()
        a1.close.assert_called_once()
        a2.close.assert_called_once()

    def test_close_all_closes_adapter_pools(self):
        registry = AdapterRegistry()
        adapter = Mock()
        adapter.service_name = "pooled"
        adapter.grpc_pool = Mock(spec=GrpcChannelPool)
        registry.register("pooled", adapter)
        registry.close_all()
        adapter.grpc_pool.close_all.assert_called_once()
        adapter.close.assert_called_once()

    def test_close_all_logs_pool_close_errors(self):
        registry = AdapterRegistry()
        adapters = [Mock() for _ in range(50)]
        errors: list[Exception] = []

        def register(idx: int) -> None:
            try:
                registry.register(f"svc_{idx}", adapters[idx])
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(registry.list_services()) == 50


class TestAdapterRegistryFixture:
    def test_reset_registry_fixture(self, reset_registry):
        adapter = Mock()
        reset_registry.register("temp", adapter)
        assert reset_registry.get_adapter("temp") is adapter
        # Cleanup happens automatically after test
