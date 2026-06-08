"""
Tests for django_grpc_admin.registry module.
"""
from unittest.mock import Mock

from django_grpc_admin.registry import AdapterRegistry, adapter_registry


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


class TestAdapterRegistryFixture:
    def test_reset_registry_fixture(self, reset_registry):
        adapter = Mock()
        reset_registry.register("temp", adapter)
        assert reset_registry.get_adapter("temp") is adapter
        # Cleanup happens automatically after test
