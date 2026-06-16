"""
Tests for django_admin_grpc.async_adapter module.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import grpc
import pytest

from django_admin_grpc.async_adapter import (
    AsyncAdapterRegistry,
    BaseAsyncGrpcServiceAdapter,
    async_adapter_registry,
    ensure_aio_initialized,
)
from django_admin_grpc.exceptions import GrpcBatchPartialError
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.resources import (
    BaseGrpcResource,
    CharFieldConfig,
    IntegerFieldConfig,
)


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
            with (
                patch.object(grpc.aio, "init_grpc_aio", init),
                pytest.raises(RuntimeError, match="boom"),
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
        with patch(
            "django_admin_grpc.async_adapter.grpc.aio.insecure_channel", return_value=mock_channel
        ):
            channel = await adapter.channel()
            assert channel is mock_channel

    async def test_channel_created_lazily_secure(self):
        class SecureAdapter(MinimalAsyncAdapter):
            credentials = grpc.local_channel_credentials()

        adapter = SecureAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        with patch(
            "django_admin_grpc.async_adapter.grpc.aio.secure_channel", return_value=mock_channel
        ):
            channel = await adapter.channel()
            assert channel is mock_channel

    async def test_channel_is_cached(self):
        adapter = MinimalAsyncAdapter()
        mock_channel = AsyncMock(spec=grpc.aio.Channel)
        with patch(
            "django_admin_grpc.async_adapter.grpc.aio.insecure_channel", return_value=mock_channel
        ):
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


# ── Bulk operation tests (async) ─────────────────────────────────────────


class AsyncBulkResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "asyncbulkitem"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class CountingAsyncAdapter(BaseAsyncGrpcServiceAdapter):
    """Async adapter that records every create/update/delete call."""

    service_name = "async_counting"
    target = "svc:50051"

    def __init__(self):
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self._raise_on_create: set[int] = set()
        self._raise_on_update: set[Any] = set()
        self._raise_on_delete: set[Any] = set()

    async def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    async def get(self, resource_class, pk):
        return None

    async def create(self, resource_class, data):
        self.created.append(data)
        if id(data) in self._raise_on_create:
            raise RuntimeError("create failed")
        return resource_class(**data)

    async def update(self, resource_class, pk, data):
        self.updated.append((pk, data))
        if pk in self._raise_on_update:
            raise RuntimeError("update failed")
        return resource_class(**data)

    async def delete(self, resource_class, pk):
        self.deleted.append(pk)
        if pk in self._raise_on_delete:
            raise RuntimeError("delete failed")
        return True


@pytest.mark.asyncio
class TestAsyncBulkCreate:
    async def test_empty_input_returns_empty(self):
        adapter = CountingAsyncAdapter()
        assert await adapter.bulk_create(AsyncBulkResource, []) == []

    async def test_creates_all(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = await adapter.bulk_create(AsyncBulkResource, items)
        assert len(result) == 2
        assert [r.id for r in result] == [1, 2]
        assert adapter.created == items

    async def test_chunks_input(self):
        adapter = CountingAsyncAdapter()
        adapter.batch_size = 2
        items = [{"id": i, "name": f"n{i}"} for i in range(5)]
        result = await adapter.bulk_create(AsyncBulkResource, items)
        assert len(result) == 5
        assert len(adapter.created) == 5

    async def test_partial_failure_raises_partial_error(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(3)]
        # Mark the second item to fail.
        adapter._raise_on_create.add(id(items[1]))
        with pytest.raises(GrpcBatchPartialError) as info:
            await adapter.bulk_create(AsyncBulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_create"
        assert len(exc.succeeded) == 2
        assert len(exc.failed) == 1

    async def test_batch_size_override(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(6)]
        result = await adapter.bulk_create(AsyncBulkResource, items, batch_size=2)
        assert len(result) == 6

    async def test_partial_failure_log_excludes_payload(self, caplog):
        """The warning log for async bulk_create partial failures must not
        include the raw input payload."""
        import logging

        adapter = CountingAsyncAdapter()
        items = [
            {"id": 1, "name": "secret-1", "token": "TOPSECRET"},
            {"id": 2, "name": "secret-2", "token": "TOPSECRET"},
        ]
        adapter._raise_on_create.add(id(items[0]))
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.async_adapter"),
            pytest.raises(GrpcBatchPartialError),
        ):
            await adapter.bulk_create(AsyncBulkResource, items)
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "secret-1" not in joined
        assert "secret-2" not in joined


@pytest.mark.asyncio
class TestAsyncBulkUpdate:
    async def test_empty_input_returns_empty(self):
        adapter = CountingAsyncAdapter()
        assert await adapter.bulk_update(AsyncBulkResource, []) == []

    async def test_updates_all(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = await adapter.bulk_update(AsyncBulkResource, items)
        assert len(result) == 2
        assert adapter.updated == [("1", items[0]), ("2", items[1])]

    async def test_chunks_input(self):
        adapter = CountingAsyncAdapter()
        adapter.batch_size = 2
        items = [{"id": i, "name": f"n{i}"} for i in range(5)]
        result = await adapter.bulk_update(AsyncBulkResource, items)
        assert len(result) == 5
        assert len(adapter.updated) == 5

    async def test_missing_pk_recorded_as_failure(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": 1, "name": "a"}, {"name": "b"}, {"id": 3, "name": "c"}]
        with pytest.raises(GrpcBatchPartialError) as info:
            await adapter.bulk_update(AsyncBulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_update"
        assert sorted(exc.succeeded) == [1, 3]
        # The missing-pk item is recorded as a failure with a ``ValueError``.
        assert None in exc.failed
        assert isinstance(exc.failed[None], ValueError)

    async def test_partial_failure_raises_partial_error(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        adapter._raise_on_update.add("2")
        with pytest.raises(GrpcBatchPartialError) as info:
            await adapter.bulk_update(AsyncBulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_update"
        assert exc.succeeded == [1]
        # Pk keys in the failed dict mirror what the caller passed.
        assert 2 in exc.failed
        assert isinstance(exc.failed[2], RuntimeError)

    async def test_respects_custom_pk_field(self):
        class CustomPkResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "async_custompk"
                pk_field = "rule_id"

            fields = [
                CharFieldConfig(name="rule_id"),
                CharFieldConfig(name="value"),
            ]

        adapter = CountingAsyncAdapter()
        items = [{"rule_id": "r1", "value": "x"}]
        result = await adapter.bulk_update(CustomPkResource, items)
        assert result[0].rule_id == "r1"
        assert adapter.updated == [("r1", items[0])]

    async def test_batch_size_override(self):
        adapter = CountingAsyncAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(6)]
        result = await adapter.bulk_update(AsyncBulkResource, items, batch_size=2)
        assert len(result) == 6

    async def test_missing_pk_log_excludes_payload(self, caplog):
        """The warning log for async bulk_update missing-pk items must not
        include the raw input payload."""
        import logging

        adapter = CountingAsyncAdapter()
        items = [
            {"id": 1, "name": "secret-1", "token": "TOPSECRET"},
            {"name": "no-pk", "token": "TOPSECRET"},
        ]
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.async_adapter"),
            pytest.raises(GrpcBatchPartialError),
        ):
            await adapter.bulk_update(AsyncBulkResource, items)
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "secret-1" not in joined
        assert "no-pk" not in joined

    async def test_partial_failure_log_excludes_payload(self, caplog):
        """The warning log for async bulk_update partial failures must not
        include the raw input payload."""
        import logging

        adapter = CountingAsyncAdapter()
        items = [
            {"id": 1, "name": "ok-1", "token": "TOPSECRET"},
            {"id": 2, "name": "fail-2", "token": "TOPSECRET"},
        ]
        adapter._raise_on_update.add("2")
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.async_adapter"),
            pytest.raises(GrpcBatchPartialError),
        ):
            await adapter.bulk_update(AsyncBulkResource, items)
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "ok-1" not in joined
        assert "fail-2" not in joined


@pytest.mark.asyncio
class TestAsyncBulkDelete:
    async def test_empty_input_returns_empty(self):
        adapter = CountingAsyncAdapter()
        result = await adapter.bulk_delete(AsyncBulkResource, [])
        assert result == {"deleted": 0, "failed": []}

    async def test_deletes_all(self):
        adapter = CountingAsyncAdapter()
        result = await adapter.bulk_delete(AsyncBulkResource, ["1", "2", "3"])
        assert result == {"deleted": 3, "failed": []}
        assert adapter.deleted == ["1", "2", "3"]

    async def test_chunks_input(self):
        adapter = CountingAsyncAdapter()
        adapter.batch_size = 2
        result = await adapter.bulk_delete(AsyncBulkResource, ["1", "2", "3", "4", "5"])
        assert result == {"deleted": 5, "failed": []}

    async def test_partial_failure_raises_partial_error(self):
        adapter = CountingAsyncAdapter()
        adapter._raise_on_delete.add("2")
        with pytest.raises(GrpcBatchPartialError) as info:
            await adapter.bulk_delete(AsyncBulkResource, ["1", "2", "3"])
        exc = info.value
        assert exc.operation == "bulk_delete"
        assert exc.succeeded == ["1", "3"]
        assert "2" in exc.failed
        assert isinstance(exc.failed["2"], RuntimeError)

    async def test_batch_size_override(self):
        adapter = CountingAsyncAdapter()
        result = await adapter.bulk_delete(AsyncBulkResource, ["1", "2", "3"], batch_size=1)
        assert result == {"deleted": 3, "failed": []}
        assert adapter.deleted == ["1", "2", "3"]
