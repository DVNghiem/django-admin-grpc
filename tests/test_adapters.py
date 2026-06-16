"""
Tests for django_admin_grpc.adapters module.
"""
from typing import Any
from unittest.mock import Mock, patch

import grpc
import pytest

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.exceptions import GrpcBatchPartialError
from django_admin_grpc.paginator import PagedResult
from django_admin_grpc.pool import GrpcChannelPool
from django_admin_grpc.resources import (
    BaseGrpcResource,
    CharFieldConfig,
    IntegerFieldConfig,
)


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


# ── Bulk operation tests ─────────────────────────────────────────────────


class BulkResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "bulkitem"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class CountingAdapter(BaseGrpcServiceAdapter):
    """Adapter that records every create/update/delete call."""

    service_name = "counting"

    def __init__(self):
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self._raise_on_create: set[int] = set()
        self._raise_on_update: set[Any] = set()
        self._raise_on_delete: set[Any] = set()

    def list(self, resource_class, page=1, page_size=25, filters=None):
        return PagedResult(items=[])

    def get(self, resource_class, pk):
        return None

    def create(self, resource_class, data):
        self.created.append(data)
        if id(data) in self._raise_on_create:
            raise RuntimeError("create failed")
        return resource_class(**data)

    def update(self, resource_class, pk, data):
        self.updated.append((pk, data))
        if pk in self._raise_on_update:
            raise RuntimeError("update failed")
        return resource_class(**data)

    def delete(self, resource_class, pk):
        self.deleted.append(pk)
        if pk in self._raise_on_delete:
            raise RuntimeError("delete failed")
        return True


class TestBulkCreate:
    def test_empty_input_returns_empty(self):
        adapter = CountingAdapter()
        assert adapter.bulk_create(BulkResource, []) == []

    def test_creates_all(self):
        adapter = CountingAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = adapter.bulk_create(BulkResource, items)
        assert len(result) == 2
        assert [r.id for r in result] == [1, 2]
        assert adapter.created == items

    def test_chunks_input(self):
        adapter = CountingAdapter()
        adapter.batch_size = 2
        items = [{"id": i, "name": f"n{i}"} for i in range(5)]
        result = adapter.bulk_create(BulkResource, items)
        assert len(result) == 5
        assert len(adapter.created) == 5

    def test_partial_failure_raises_partial_error(self):
        adapter = CountingAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(3)]
        # Mark the second item to fail.
        adapter._raise_on_create.add(id(items[1]))
        with pytest.raises(GrpcBatchPartialError) as info:
            adapter.bulk_create(BulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_create"
        assert len(exc.succeeded) == 2
        assert len(exc.failed) == 1

    def test_batch_size_override(self):
        adapter = CountingAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(6)]
        result = adapter.bulk_create(BulkResource, items, batch_size=2)
        assert len(result) == 6

    def test_partial_failure_log_excludes_payload(self, caplog):
        """The warning log for partial bulk_create failures must not include
        the raw input payload — only the resource name, item index, and
        exception info."""
        import logging

        adapter = CountingAdapter()
        items = [
            {"id": 1, "name": "secret-1", "token": "TOPSECRET"},
            {"id": 2, "name": "secret-2", "token": "TOPSECRET"},
        ]
        adapter._raise_on_create.add(id(items[0]))
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.adapters"),
            pytest.raises(GrpcBatchPartialError),
        ):
            adapter.bulk_create(BulkResource, items)
        # At least one warning was logged for the failure.
        assert any(
            "bulk_create" in record.message for record in caplog.records
        )
        # The log message and any of its arguments must not include the
        # sensitive payload values.
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "secret-1" not in joined
        assert "secret-2" not in joined


class TestBulkUpdate:
    def test_empty_input_returns_empty(self):
        adapter = CountingAdapter()
        assert adapter.bulk_update(BulkResource, []) == []

    def test_updates_all(self):
        adapter = CountingAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = adapter.bulk_update(BulkResource, items)
        assert len(result) == 2
        assert adapter.updated == [("1", items[0]), ("2", items[1])]

    def test_chunks_input(self):
        adapter = CountingAdapter()
        adapter.batch_size = 2
        items = [{"id": i, "name": f"n{i}"} for i in range(5)]
        result = adapter.bulk_update(BulkResource, items)
        assert len(result) == 5
        assert len(adapter.updated) == 5

    def test_missing_pk_recorded_as_failure(self):
        adapter = CountingAdapter()
        items = [{"id": 1, "name": "a"}, {"name": "b"}, {"id": 3, "name": "c"}]
        with pytest.raises(GrpcBatchPartialError) as info:
            adapter.bulk_update(BulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_update"
        assert sorted(exc.succeeded) == [1, 3]
        # The missing-pk item is recorded as a failure with a ``ValueError``.
        assert None in exc.failed
        assert isinstance(exc.failed[None], ValueError)

    def test_partial_failure_raises_partial_error(self):
        adapter = CountingAdapter()
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        adapter._raise_on_update.add("2")
        with pytest.raises(GrpcBatchPartialError) as info:
            adapter.bulk_update(BulkResource, items)
        exc = info.value
        assert exc.operation == "bulk_update"
        assert exc.succeeded == [1]
        # Pk keys in the failed dict mirror what the caller passed.
        assert 2 in exc.failed
        assert isinstance(exc.failed[2], RuntimeError)

    def test_respects_custom_pk_field(self):
        class CustomPkResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "custompk"
                pk_field = "rule_id"

            fields = [
                CharFieldConfig(name="rule_id"),
                CharFieldConfig(name="value"),
            ]

        adapter = CountingAdapter()
        items = [{"rule_id": "r1", "value": "x"}]
        result = adapter.bulk_update(CustomPkResource, items)
        assert result[0].rule_id == "r1"
        assert adapter.updated == [("r1", items[0])]

    def test_batch_size_override(self):
        adapter = CountingAdapter()
        items = [{"id": i, "name": f"n{i}"} for i in range(6)]
        result = adapter.bulk_update(BulkResource, items, batch_size=2)
        assert len(result) == 6

    def test_missing_pk_log_excludes_payload(self, caplog):
        """The warning log for missing-pk bulk_update items must not include
        the raw input payload — only the resource name and pk field."""
        import logging

        adapter = CountingAdapter()
        items = [
            {"id": 1, "name": "secret-1", "token": "TOPSECRET"},
            {"name": "no-pk", "token": "TOPSECRET"},
        ]
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.adapters"),
            pytest.raises(GrpcBatchPartialError),
        ):
            adapter.bulk_update(BulkResource, items)
        assert any(
            "missing pk" in record.message for record in caplog.records
        )
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "secret-1" not in joined
        assert "no-pk" not in joined

    def test_partial_failure_log_excludes_payload(self, caplog):
        """The warning log for partial bulk_update failures must not include
        the raw input payload — only the resource name, PK, and exception."""
        import logging

        adapter = CountingAdapter()
        items = [
            {"id": 1, "name": "ok-1", "token": "TOPSECRET"},
            {"id": 2, "name": "fail-2", "token": "TOPSECRET"},
        ]
        adapter._raise_on_update.add("2")
        with (
            caplog.at_level(logging.WARNING, logger="django_admin_grpc.adapters"),
            pytest.raises(GrpcBatchPartialError),
        ):
            adapter.bulk_update(BulkResource, items)
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "TOPSECRET" not in joined
        assert "ok-1" not in joined
        assert "fail-2" not in joined


class TestBulkDelete:
    def test_empty_input_returns_empty(self):
        adapter = CountingAdapter()
        result = adapter.bulk_delete(BulkResource, [])
        assert result == {"deleted": 0, "failed": []}

    def test_deletes_all(self):
        adapter = CountingAdapter()
        result = adapter.bulk_delete(BulkResource, ["1", "2", "3"])
        assert result == {"deleted": 3, "failed": []}
        assert adapter.deleted == ["1", "2", "3"]

    def test_chunks_input(self):
        adapter = CountingAdapter()
        adapter.batch_size = 2
        result = adapter.bulk_delete(BulkResource, ["1", "2", "3", "4", "5"])
        assert result == {"deleted": 5, "failed": []}

    def test_partial_failure_raises_partial_error(self):
        adapter = CountingAdapter()
        adapter._raise_on_delete.add("2")
        with pytest.raises(GrpcBatchPartialError) as info:
            adapter.bulk_delete(BulkResource, ["1", "2", "3"])
        exc = info.value
        assert exc.operation == "bulk_delete"
        assert exc.succeeded == ["1", "3"]
        assert "2" in exc.failed
        assert isinstance(exc.failed["2"], RuntimeError)

    def test_batch_size_override(self):
        adapter = CountingAdapter()
        result = adapter.bulk_delete(BulkResource, ["1", "2", "3"], batch_size=1)
        assert result == {"deleted": 3, "failed": []}
        assert adapter.deleted == ["1", "2", "3"]


class TestGetPkFieldName:
    def test_default_pk_field(self):
        class DefaultPkResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "defaultpk"

            fields = [IntegerFieldConfig(name="id")]

        assert (
            BaseGrpcServiceAdapter._get_pk_field_name(DefaultPkResource) == "id"
        )

    def test_custom_pk_field(self):
        class CustomPkResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "custompk"
                pk_field = "rule_id"

            fields = [CharFieldConfig(name="rule_id")]

        assert (
            BaseGrpcServiceAdapter._get_pk_field_name(CustomPkResource) == "rule_id"
        )
