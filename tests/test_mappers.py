"""
Tests for django_grpc_admin.mappers module.
"""

import pytest

from django_grpc_admin.mappers import BaseGrpcMapper, DefaultGrpcMapper
from django_grpc_admin.resources import (
    BaseGrpcResource,
    CharFieldConfig,
    IntegerFieldConfig,
)


class DummyResource(BaseGrpcResource):
    class Meta:
        app_label = "test"
        model_name = "dummy"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
    ]


class TestDefaultGrpcMapper:
    def test_to_create_request_pass_through(self):
        mapper = DefaultGrpcMapper()
        data = {"name": "Widget", "price": 10.0}
        result = mapper.to_create_request(DummyResource, data)
        assert result == data

    def test_to_update_request_includes_pk(self):
        mapper = DefaultGrpcMapper()
        data = {"name": "Updated"}
        result = mapper.to_update_request(DummyResource, "42", data)
        assert result == {"pk": "42", "name": "Updated"}

    def test_from_response_delegates_to_resource(self):
        mapper = DefaultGrpcMapper()
        response = {"id": 1, "name": "Test"}
        result = mapper.from_response(DummyResource, response)
        assert isinstance(result, DummyResource)
        assert result.id == 1
        assert result.name == "Test"

    def test_to_list_request(self):
        mapper = DefaultGrpcMapper()
        result = mapper.to_list_request(DummyResource, 2, 50, {"active": True})
        assert result == {"page": 2, "page_size": 50, "filters": {"active": True}}

    def test_to_list_request_default_filters(self):
        mapper = DefaultGrpcMapper()
        result = mapper.to_list_request(DummyResource, 1, 25)
        assert result == {"page": 1, "page_size": 25, "filters": {}}

    def test_from_list_response_with_dict(self):
        mapper = DefaultGrpcMapper()
        response = {"items": [{"id": 1}], "total": 1, "next_cursor": "c1"}
        result = mapper.from_list_response(DummyResource, response)
        assert result["items"] == [{"id": 1}]
        assert result["total"] == 1
        assert result["next_cursor"] == "c1"

    def test_from_list_response_with_object(self):
        mapper = DefaultGrpcMapper()

        class ProtoResponse:
            items = [{"id": 1}]
            total = 5
            next_cursor = "next"

        result = mapper.from_list_response(DummyResource, ProtoResponse())
        assert result["items"] == [{"id": 1}]
        assert result["total"] == 5
        assert result["next_cursor"] == "next"

    def test_from_list_response_with_object_no_total(self):
        mapper = DefaultGrpcMapper()

        class ProtoResponse:
            items = [{"id": 1}, {"id": 2}]

        result = mapper.from_list_response(DummyResource, ProtoResponse())
        assert result["total"] == 2
        assert result["next_cursor"] is None


class TestBaseGrpcMapperAbstract:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseGrpcMapper()

    def test_subclass_must_implement_methods(self):
        class BadMapper(BaseGrpcMapper):
            pass

        with pytest.raises(TypeError):
            BadMapper()
