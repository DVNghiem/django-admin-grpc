"""
Tests for django_admin_grpc.context_providers and adapter metadata.
"""

from __future__ import annotations

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.context_providers import (
    AuthTokenProvider,
    CorrelationIdProvider,
    TenantContextProvider,
)
from django_admin_grpc.resources import BaseGrpcResource


class DummyRequest:
    def __init__(self, meta=None, tenant=None):
        self.META = meta or {}
        self.tenant = tenant


class TestTenantContextProvider:
    def test_reads_request_tenant_id(self):
        request = DummyRequest(tenant=DummyObject(id="t-123"))
        assert TenantContextProvider()(request) == {"x-tenant-id": "t-123"}

    def test_reads_header(self):
        request = DummyRequest(meta={"HTTP_X_TENANT_ID": "t-456"})
        assert TenantContextProvider()(request) == {"x-tenant-id": "t-456"}

    def test_custom_header_setting(self, settings):
        settings.GRPC_ADMIN_TENANT_HEADER = "x-org-id"
        request = DummyRequest(meta={"HTTP_X_ORG_ID": "org-1"})
        assert TenantContextProvider()(request) == {"x-tenant-id": "org-1"}

    def test_missing_tenant_returns_empty(self):
        request = DummyRequest()
        assert TenantContextProvider()(request) == {}


class TestAuthTokenProvider:
    def test_injects_authorization(self):
        request = DummyRequest(meta={"HTTP_AUTHORIZATION": "Bearer token"})
        assert AuthTokenProvider()(request) == {"authorization": "Bearer token"}

    def test_missing_returns_empty(self):
        request = DummyRequest()
        assert AuthTokenProvider()(request) == {}


class TestCorrelationIdProvider:
    def test_reuses_existing_header(self):
        request = DummyRequest(meta={"HTTP_X_REQUEST_ID": "rid-1"})
        assert CorrelationIdProvider()(request) == {"x-request-id": "rid-1"}
        assert request._grpc_request_id == "rid-1"

    def test_generates_uuid_when_missing(self):
        request = DummyRequest()
        result = CorrelationIdProvider()(request)
        assert "x-request-id" in result
        assert len(result["x-request-id"]) == 36
        assert request._grpc_request_id == result["x-request-id"]


class DummyObject:
    def __init__(self, id=None):
        self.id = id


class SampleResource(BaseGrpcResource):
    class Meta:
        app_label = "test"
        model_name = "sample"

    fields = []


class TestAdapterMetadata:
    def test_get_grpc_metadata_merges_providers(self, settings):
        settings.GRPC_ADMIN_CONTEXT_PROVIDERS = [
            lambda r: {"x-global": "1"},
        ]

        class Adapter(BaseGrpcServiceAdapter):
            service_name = "test"
            grpc_context_providers = [lambda r: {"x-local": "2"}]

            def list(self, resource_class, page=1, page_size=25, filters=None, request=None):
                return None  # type: ignore[return-value]

            def get(self, resource_class, pk, request=None):
                return None

        adapter = Adapter()
        metadata = adapter.get_grpc_metadata(DummyRequest())
        assert metadata == [("x-global", "1"), ("x-local", "2")]

    def test_get_grpc_metadata_overrides_global_with_local(self, settings):
        settings.GRPC_ADMIN_CONTEXT_PROVIDERS = [
            lambda r: {"x-key": "global"},
        ]

        class Adapter(BaseGrpcServiceAdapter):
            service_name = "test"
            grpc_context_providers = [lambda r: {"x-key": "local"}]

            def list(self, resource_class, page=1, page_size=25, filters=None, request=None):
                return None  # type: ignore[return-value]

            def get(self, resource_class, pk, request=None):
                return None

        adapter = Adapter()
        metadata = adapter.get_grpc_metadata(DummyRequest())
        assert metadata == [("x-key", "local")]
