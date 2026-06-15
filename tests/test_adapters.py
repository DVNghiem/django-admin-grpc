"""
Tests for django_admin_grpc.adapters module.
"""
from unittest.mock import Mock, patch

import grpc
import pytest

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.pool import GrpcChannelPool


class MinimalAdapter(BaseGrpcServiceAdapter):
    service_name = "minimal"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    def get(self, resource_class, pk):
        return None


class FullAdapter(BaseGrpcServiceAdapter):
    service_name = "full"

    def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    def get(self, resource_class, pk):
        return None

    def create(self, resource_class, data):
        return Mock()

    def update(self, resource_class, pk, data):
        return Mock()

    def delete(self, resource_class, pk):
        return True


class TestBaseGrpcServiceAdapterAbstract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseGrpcServiceAdapter()

    def test_subclass_must_implement_list(self):
        class BadAdapter(BaseGrpcServiceAdapter):
            def get(self, resource_class, pk):
                return None

        with pytest.raises(TypeError):
            BadAdapter()

    def test_subclass_must_implement_get(self):
        class BadAdapter(BaseGrpcServiceAdapter):
            def list(self, resource_class, page=1, page_size=25, filters=None):
                return PagedResult(items=[])

        with pytest.raises(TypeError):
            BadAdapter()


class TestBaseGrpcServiceAdapterCapabilities:
    def test_supports_create_false_by_default(self):
        adapter = MinimalAdapter()
        assert adapter.supports_create is False

    def test_supports_update_false_by_default(self):
        adapter = MinimalAdapter()
        assert adapter.supports_update is False

    def test_supports_delete_false_by_default(self):
        adapter = MinimalAdapter()
        assert adapter.supports_delete is False

    def test_supports_create_true_when_overridden(self):
        adapter = FullAdapter()
        assert adapter.supports_create is True

    def test_supports_update_true_when_overridden(self):
        adapter = FullAdapter()
        assert adapter.supports_update is True

    def test_supports_delete_true_when_overridden(self):
        adapter = FullAdapter()
        assert adapter.supports_delete is True


class TestBaseGrpcServiceAdapterDefaultMethods:
    def test_create_raises_not_implemented(self):
        adapter = MinimalAdapter()
        with pytest.raises(NotImplementedError, match="does not support create"):
            adapter.create(Mock(), {})

    def test_update_raises_not_implemented(self):
        adapter = MinimalAdapter()
        with pytest.raises(NotImplementedError, match="does not support update"):
            adapter.update(Mock(), "1", {})

    def test_delete_raises_not_implemented(self):
        adapter = MinimalAdapter()
        with pytest.raises(NotImplementedError, match="does not support delete"):
            adapter.delete(Mock(), "1")

    def test_close_is_no_op(self):
        adapter = MinimalAdapter()
        adapter.close()  # should not raise

    def test_close_closes_channel(self):
        adapter = MinimalAdapter()
        mock_channel = Mock(spec=grpc.Channel)
        adapter._channel = mock_channel
        adapter.close()
        mock_channel.close.assert_called_once()

    def test_create_channel_wraps_and_returns(self):
        adapter = MinimalAdapter()
        raw_channel = Mock(spec=grpc.Channel)
        wrapped = Mock(spec=grpc.Channel)

        with (
            patch("django_admin_grpc.adapters.grpc.insecure_channel", return_value=raw_channel),
            patch.object(adapter, "_wrap_channel", return_value=wrapped),
        ):
            result = adapter._create_channel("svc:50051")

        assert result is wrapped

    def test_create_channel_closes_raw_when_wrap_raises(self):
        adapter = MinimalAdapter()
        raw_channel = Mock(spec=grpc.Channel)

        with (
            patch("django_admin_grpc.adapters.grpc.insecure_channel", return_value=raw_channel),
            patch.object(adapter, "_wrap_channel", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            adapter._create_channel("svc:50051")

        raw_channel.close.assert_called_once()

    def test_batch_get_default_loops_get(self):
        class TrackingAdapter(MinimalAdapter):
            def __init__(self):
                super().__init__()
                self.get_calls = []

            def get(self, resource_class, pk):
                self.get_calls.append(pk)
                obj = Mock()
                obj.pk = pk
                return obj

        tracking = TrackingAdapter()
        resource_class = Mock()
        result = tracking.batch_get(resource_class, ["1", "2", "3"])
        assert tracking.get_calls == ["1", "2", "3"]
        assert set(result.keys()) == {"1", "2", "3"}


class TestBaseGrpcServiceAdapterHelpers:
    def test_map_rpc_error(self):
        adapter = MinimalAdapter()

        class MockRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.NOT_FOUND

            def details(self):
                return "item not found"

        mock_exc = MockRpcError()
        result = adapter._map_rpc_error(mock_exc)
        assert isinstance(result, Exception)
        assert "item not found" in str(result)

    def test_wrap_channel(self):
        adapter = MinimalAdapter()
        mock_channel = Mock(spec=grpc.Channel)

        with patch("django_admin_grpc.adapters.grpc.intercept_channel") as mock_intercept:
            mock_intercept.return_value = Mock(spec=grpc.Channel)
            with patch.object(
                adapter, "_trace_context_provider", return_value=lambda: {}
            ):
                result = adapter._wrap_channel(mock_channel)
                mock_intercept.assert_called_once()
                assert result is mock_intercept.return_value

    def test_trace_context_provider_none(self):
        adapter = MinimalAdapter()
        with patch(
            "django_admin_grpc.settings.get_setting", return_value=None
        ):
            provider = adapter._trace_context_provider()
            assert provider() == {}

    def test_trace_context_provider_callable(self):
        adapter = MinimalAdapter()
        fn = lambda: {"x-trace-id": "abc"}  # noqa: E731
        with patch(
            "django_admin_grpc.settings.get_setting", return_value=fn
        ):
            provider = adapter._trace_context_provider()
            assert provider is fn

    def test_trace_context_provider_dotted_path(self):
        adapter = MinimalAdapter()
        with patch(
            "django_admin_grpc.settings.get_setting",
            return_value="tests.test_adapters.dummy_provider",
        ), patch(
            "django.utils.module_loading.import_string",
            return_value=lambda: {"x-trace-id": "xyz"},
        ) as mock_import:
            provider = adapter._trace_context_provider()
            mock_import.assert_called_once_with("tests.test_adapters.dummy_provider")
            assert provider() == {"x-trace-id": "xyz"}


def dummy_provider():
    return {}


class TestBaseGrpcServiceAdapterChannel:
    def test_get_channel_yields_self_channel_without_pool(self):
        class ChannelAdapter(MinimalAdapter):
            def __init__(self):
                super().__init__()
                self._mock_channel = Mock(spec=grpc.Channel)

            @property
            def channel(self):
                return self._mock_channel

        adapter = ChannelAdapter()
        with adapter.get_channel() as channel:
            assert channel is adapter.channel

    def test_get_channel_borrows_from_pool(self):
        pool_channel = Mock(spec=grpc.Channel)
        pool = Mock(spec=GrpcChannelPool)
        pool.get_channel.return_value.__enter__ = Mock(return_value=pool_channel)
        pool.get_channel.return_value.__exit__ = Mock(return_value=False)

        adapter = MinimalAdapter()
        adapter.grpc_pool = pool

        with adapter.get_channel() as channel:
            assert channel is pool_channel

        pool.get_channel.assert_called_once()
