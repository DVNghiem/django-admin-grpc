"""
Tests for django_admin_grpc.adapters module.
"""
from unittest.mock import Mock, patch

import grpc
import pytest

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult


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
