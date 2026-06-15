"""
Tests for django_admin_grpc.async_adapter module.
"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import grpc
import pytest

from django_admin_grpc.async_adapter import (
    AsyncAdapterRegistry,
    BaseAsyncGrpcServiceAdapter,
    async_adapter_registry,
    ensure_aio_initialized,
)
from django_admin_grpc.paginator import PagedResult


class MinimalAsyncAdapter(BaseAsyncGrpcServiceAdapter):
    service_name = "minimal"
    target = "svc:50051"

    async def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    async def get(self, resource_class, pk):
        return None


class FullAsyncAdapter(BaseAsyncGrpcServiceAdapter):
    service_name = "full"
    target = "svc:50051"

    async def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    async def get(self, resource_class, pk):
        return None

    async def create(self, resource_class, data):
        return Mock()

    async def update(self, resource_class, pk, data):
        return Mock()

    async def delete(self, resource_class, pk):
        return True


class TestEnsureAioInitialized:
    def test_idempotent(self):
        ensure_aio_initialized()
        ensure_aio_initialized()

    def test_handles_already_initialized(self):
        init = Mock(side_effect=RuntimeError("already initialized"))

        async def _call():
            with patch.object(grpc.aio, "init_grpc_aio", init):
                ensure_aio_initialized()

        asyncio.run(_call())
        # Reset flag so other tests are not affected.
        from django_admin_grpc import async_adapter

        async_adapter._aio_initialized = False

    def test_reraises_unexpected_runtime_error(self):
        init = Mock(side_effect=RuntimeError("boom"))

        async def _call():
            with patch.object(grpc.aio, "init_grpc_aio", init), pytest.raises(
                RuntimeError, match="boom"
            ):
                ensure_aio_initialized()

        asyncio.run(_call())
        from django_admin_grpc import async_adapter

        async_adapter._aio_initialized = False


@pytest.mark.asyncio
class TestBaseAsyncGrpcServiceAdapter:
    async def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseAsyncGrpcServiceAdapter()

    async def test_subclass_must_implement_list(self):
        class BadAdapter(BaseAsyncGrpcServiceAdapter):
            target = "svc:50051"

            async def get(self, resource_class, pk):
                return None

        with pytest.raises(TypeError):
            BadAdapter()

    async def test_subclass_must_implement_get(self):
        class BadAdapter(BaseAsyncGrpcServiceAdapter):
            target = "svc:50051"

            async def list(self, resource_class, page=1, page_size=25, filters=None):
                return PagedResult(items=[])

        with pytest.raises(TypeError):
            BadAdapter()

    async def test_supports_flags(self):
        minimal = MinimalAsyncAdapter()
        full = FullAsyncAdapter()
        assert minimal.supports_create is False
        assert minimal.supports_update is False
        assert minimal.supports_delete is False
        assert full.supports_create is True
        assert full.supports_update is True
        assert full.supports_delete is True

    async def test_create_raises_not_implemented(self):
        adapter = MinimalAsyncAdapter()
        with pytest.raises(NotImplementedError, match="does not support create"):
            await adapter.create(Mock(), {})

    async def test_update_raises_not_implemented(self):
        adapter = MinimalAsyncAdapter()
        with pytest.raises(NotImplementedError, match="does not support update"):
            await adapter.update(Mock(), "1", {})

    async def test_delete_raises_not_implemented(self):
        adapter = MinimalAsyncAdapter()
        with pytest.raises(NotImplementedError, match="does not support delete"):
            await adapter.delete(Mock(), "1")

    async def test_channel_created_lazily_insecure(self):
        adapter = MinimalAsyncAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        with patch("django_admin_grpc.async_adapter.grpc.aio.insecure_channel", return_value=mock_channel):
            channel = await adapter.channel()
            assert channel is mock_channel

    async def test_channel_created_lazily_secure(self):
        class SecureAdapter(MinimalAsyncAdapter):
            credentials = grpc.local_channel_credentials()

        adapter = SecureAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        with patch("django_admin_grpc.async_adapter.grpc.aio.secure_channel", return_value=mock_channel):
            channel = await adapter.channel()
            assert channel is mock_channel

    async def test_channel_is_cached(self):
        adapter = MinimalAsyncAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        with patch("django_admin_grpc.async_adapter.grpc.aio.insecure_channel", return_value=mock_channel):
            ch1 = await adapter.channel()
            ch2 = await adapter.channel()
            assert ch1 is ch2 is mock_channel

    async def test_close(self):
        adapter = MinimalAsyncAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        adapter._channel = mock_channel
        await adapter.close()
        mock_channel.close.assert_awaited_once()
        assert adapter._channel is None

    async def test_close_without_channel_is_no_op(self):
        adapter = MinimalAsyncAdapter()
        await adapter.close()

    async def test_batch_get_concurrent(self):
        class TrackingAsyncAdapter(MinimalAsyncAdapter):
            def __init__(self):
                super().__init__()
                self.get_calls = []

            async def get(self, resource_class, pk):
                self.get_calls.append(pk)
                obj = Mock()
                obj.pk = pk
                return obj

        adapter = TrackingAsyncAdapter()
        resource_class = Mock()
        result = await adapter.batch_get(resource_class, ["1", "2", "3"])
        assert sorted(adapter.get_calls) == ["1", "2", "3"]
        assert set(result.keys()) == {"1", "2", "3"}

    async def test_batch_get_empty(self):
        adapter = MinimalAsyncAdapter()
        result = await adapter.batch_get(Mock(), [])
        assert result == {}

    async def test_map_rpc_error(self):
        adapter = MinimalAsyncAdapter()

        class MockRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.NOT_FOUND

            def details(self):
                return "item not found"

        result = adapter._map_rpc_error(MockRpcError())
        assert "item not found" in str(result)


class TestAsyncAdapterRegistry:
    def test_register_and_get(self):
        registry = AsyncAdapterRegistry()
        adapter = MinimalAsyncAdapter()
        registry.register("svc", adapter)
        assert registry.get_adapter("svc") is adapter

    def test_get_missing_returns_none(self):
        registry = AsyncAdapterRegistry()
        assert registry.get_adapter("missing") is None

    def test_unregister(self):
        registry = AsyncAdapterRegistry()
        adapter = MinimalAsyncAdapter()
        registry.register("svc", adapter)
        registry.unregister("svc")
        assert registry.get_adapter("svc") is None

    def test_list_services(self):
        registry = AsyncAdapterRegistry()
        registry.register("a", MinimalAsyncAdapter())
        registry.register("b", MinimalAsyncAdapter())
        assert sorted(registry.list_services()) == ["a", "b"]

    def test_clear(self):
        registry = AsyncAdapterRegistry()
        registry.register("x", MinimalAsyncAdapter())
        registry.clear()
        assert registry.list_services() == []

    def test_freeze(self):
        registry = AsyncAdapterRegistry()
        registry.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            registry.register("svc", MinimalAsyncAdapter())

    @pytest.mark.asyncio
    async def test_close_all(self):
        registry = AsyncAdapterRegistry()
        a1 = MinimalAsyncAdapter()
        a2 = MinimalAsyncAdapter()
        registry.register("a", a1)
        registry.register("b", a2)
        await registry.close_all()

    def test_module_singleton(self):
        assert isinstance(async_adapter_registry, AsyncAdapterRegistry)
