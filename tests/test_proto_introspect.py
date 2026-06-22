"""
Tests for django_admin_grpc.proto_introspect.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from django_admin_grpc.admin import GrpcResourceAdmin
from django_admin_grpc.proto_introspect import ProtoFieldInspector
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    ChoicesFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
    JSONFieldConfig,
)


def _build_product_descriptor():
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "test.proto"
    file_proto.package = "test"

    enum_proto = file_proto.enum_type.add()
    enum_proto.name = "Status"
    for name, number in [("DRAFT", 0), ("PUBLISHED", 1)]:
        value = enum_proto.value.add()
        value.name = name
        value.number = number

    metadata_msg = file_proto.message_type.add()
    metadata_msg.name = "Metadata"
    key_field = metadata_msg.field.add()
    key_field.name = "key"
    key_field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    key_field.number = 1

    product_msg = file_proto.message_type.add()
    product_msg.name = "Product"

    fields = [
        ("id", descriptor_pb2.FieldDescriptorProto.TYPE_INT64, 1),
        ("name", descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 2),
        ("active", descriptor_pb2.FieldDescriptorProto.TYPE_BOOL, 3),
        ("price", descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT, 4),
        ("status", descriptor_pb2.FieldDescriptorProto.TYPE_ENUM, 5, ".test.Status"),
        ("tags", descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 6),
        ("metadata", descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, 7, ".test.Metadata"),
    ]
    for spec in fields:
        field = product_msg.field.add()
        field.name = spec[0]
        field.type = spec[1]
        field.number = spec[2]
        if len(spec) > 3:
            field.type_name = spec[3]
        if spec[0] == "tags":
            field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return pool.FindMessageTypeByName("test.Product")


@pytest.fixture
def product_descriptor():
    return _build_product_descriptor()


class TestProtoFieldInspector:
    def test_inspector_maps_scalar_fields(self, product_descriptor):
        inspector = ProtoFieldInspector(product_descriptor)
        configs = inspector.get_field_configs()
        by_name = {c.name: c for c in configs}

        assert len(configs) == 7
        assert isinstance(by_name["id"], IntegerFieldConfig)
        assert isinstance(by_name["name"], CharFieldConfig)
        assert isinstance(by_name["active"], BooleanFieldConfig)
        assert isinstance(by_name["price"], FloatFieldConfig)
        assert isinstance(by_name["status"], ChoicesFieldConfig)
        assert isinstance(by_name["tags"], JSONFieldConfig)
        assert isinstance(by_name["metadata"], JSONFieldConfig)

    def test_enum_choices_populated(self, product_descriptor):
        inspector = ProtoFieldInspector(product_descriptor)
        configs = {c.name: c for c in inspector.get_field_configs()}
        status = configs["status"]
        assert status.choices == [(0, "DRAFT"), (1, "PUBLISHED")]

    def test_pk_field_marked_readonly(self, product_descriptor):
        inspector = ProtoFieldInspector(product_descriptor, pk_field="id")
        configs = {c.name: c for c in inspector.get_field_configs()}
        assert configs["id"].readonly is True
        assert configs["name"].readonly is False

    def test_exclude_and_readonly(self, product_descriptor):
        inspector = ProtoFieldInspector(
            product_descriptor,
            exclude=["metadata"],
            readonly=["active"],
        )
        configs = {c.name: c for c in inspector.get_field_configs()}
        assert "metadata" not in configs
        assert configs["active"].readonly is True

    def test_field_overrides(self, product_descriptor):
        override = CharFieldConfig(name="name", max_length=120)
        inspector = ProtoFieldInspector(
            product_descriptor,
            field_overrides={"name": override},
        )
        configs = {c.name: c for c in inspector.get_field_configs()}
        assert configs["name"] is override

    def test_list_display_skips_nested_messages(self, product_descriptor):
        inspector = ProtoFieldInspector(product_descriptor)
        assert inspector.get_list_display() == [
            "id",
            "name",
            "active",
            "price",
            "status",
        ]

    def test_search_fields_returns_strings_only(self, product_descriptor):
        inspector = ProtoFieldInspector(product_descriptor)
        assert inspector.get_search_fields() == ["name"]


class TestBaseGrpcResourceFromProto:
    def test_from_proto_returns_subclass(self, product_descriptor):
        resource = BaseGrpcResource.from_proto(
            product_descriptor,
            app_label="shop",
            model_name="product",
            verbose_name="Product",
            pk_field="id",
        )
        assert issubclass(resource, BaseGrpcResource)
        assert resource.proto_descriptor is product_descriptor
        assert resource.Meta.pk_field == "id"
        assert resource.Meta.app_label == "shop"

    def test_configure_fields_from_proto(self, product_descriptor):
        class ProductResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "product"

            proto_descriptor = product_descriptor

        ProductResource.configure_fields_from_proto(pk_field="id")
        assert len(ProductResource.fields) == 7
        assert ProductResource.Meta.pk_field == "id"

    def test_invalid_pk_field_raises(self, product_descriptor):
        with pytest.raises(ValueError, match="pk_field 'missing' is not a field"):
            BaseGrpcResource.from_proto(
                product_descriptor,
                app_label="shop",
                pk_field="missing",
            )

    def test_configure_fields_from_proto_invalid_pk_field(self, product_descriptor):
        class ProductResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "product"

            proto_descriptor = product_descriptor

        with pytest.raises(ValueError, match="pk_field 'unknown' is not a field"):
            ProductResource.configure_fields_from_proto(pk_field="unknown")


class TestAutoConfigureFromProto:
    def test_admin_auto_configures_fields(self, product_descriptor):
        class ProductResource(BaseGrpcResource):
            class Meta:
                app_label = "shop"
                model_name = "product"

            proto_descriptor = product_descriptor

        class ProductAdmin(GrpcResourceAdmin):
            resource_class = ProductResource
            service_name = "products"
            auto_configure_from_proto = True
            auto_configure_from_proto_options = {"pk_field": "id"}

        admin = ProductAdmin(admin_site=None)  # type: ignore[arg-type]
        assert len(admin._resource_class.fields) == 7
        assert admin._resource_class.Meta.pk_field == "id"
