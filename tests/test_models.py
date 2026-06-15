"""
Tests for django_admin_grpc.models module.
"""
import pytest
from django.core.exceptions import FieldDoesNotExist

from django_admin_grpc.models import FakeModelMeta, GrpcFakeQuerySet, ModelWrapper
from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    IntegerFieldConfig,
)


class TestResource(BaseGrpcResource):
    class Meta:
        app_label = "test"
        model_name = "testresource"
        verbose_name = "Test Resource"
        verbose_name_plural = "Test Resources"
        pk_field = "id"

    fields = [
        IntegerFieldConfig(name="id"),
        CharFieldConfig(name="name"),
        BooleanFieldConfig(name="active"),
    ]


@pytest.fixture
def fake_meta():
    return FakeModelMeta(
        resource_class=TestResource,
        app_label="test",
        model_name="testresource",
        verbose_name="Test Resource",
        verbose_name_plural="Test Resources",
        pk_field_name="id",
    )


class TestFakeModelMeta:
    def test_basic_attributes(self, fake_meta):
        assert fake_meta.app_label == "test"
        assert fake_meta.model_name == "testresource"
        assert fake_meta.verbose_name == "Test Resource"
        assert fake_meta.verbose_name_plural == "Test Resources"
        assert fake_meta.object_name == "TestResource"
        assert fake_meta.abstract is False
        assert fake_meta.ordering == []

    def test_pk_field(self, fake_meta):
        pk = fake_meta.pk
        assert pk.name == "id"
        assert pk.attname == "id"
        assert pk.primary_key is True
        assert pk.unique is True
        assert pk.is_relation is False

    def test_get_field_found(self, fake_meta):
        field = fake_meta.get_field("name")
        assert field.name == "name"
        assert field.verbose_name == "Name"

    def test_get_field_boolean(self, fake_meta):
        field = fake_meta.get_field("active")
        assert field.name == "active"
        assert field.concrete is True

    def test_get_field_pk_alias(self, fake_meta):
        field = fake_meta.get_field("pk")
        assert field.name == "pk"
        assert field.primary_key is True

    def test_get_field_id_alias(self, fake_meta):
        field = fake_meta.get_field("id")
        assert field.name == "id"
        assert field.primary_key is True

    def test_get_field_not_found(self, fake_meta):
        with pytest.raises(FieldDoesNotExist):
            fake_meta.get_field("nonexistent")

    def test_get_field_caching(self, fake_meta):
        f1 = fake_meta.get_field("name")
        f2 = fake_meta.get_field("name")
        assert f1 is f2

    def test_get_fields_returns_empty(self, fake_meta):
        assert fake_meta.get_fields() == []

    def test_app_config_lookup(self, fake_meta):
        # auth app should exist in test settings
        assert fake_meta.app_config is not None
        assert fake_meta.app_config.label == "test"

    def test_fake_app_config(self):
        meta = FakeModelMeta(
            resource_class=TestResource,
            app_label="nonexistent_app_xyz",
            model_name="item",
            verbose_name="Item",
            verbose_name_plural="Items",
        )
        assert meta.app_config.label == "nonexistent_app_xyz"
        assert meta.app_config.name == "nonexistent_app_xyz"


class TestGrpcFakeQuerySet:
    def test_init_defaults(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert qs.model is TestResource
        assert qs._selected_pks == []

    def test_all_returns_self(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert qs.all() is qs

    def test_filter_pk_in(self):
        qs = GrpcFakeQuerySet(TestResource)
        filtered = qs.filter(pk__in=[1, 2, 3])
        assert filtered._selected_pks == [1, 2, 3]
        assert filtered.model is TestResource

    def test_filter_other_kwargs_ignored(self):
        qs = GrpcFakeQuerySet(TestResource, selected_pks=[1])
        filtered = qs.filter(name="test")
        assert filtered._selected_pks == [1]

    def test_order_by_returns_self(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert qs.order_by("name") is qs

    def test_none(self):
        qs = GrpcFakeQuerySet(TestResource, selected_pks=[1, 2])
        none_qs = qs.none()
        assert none_qs._selected_pks == []

    def test_iter(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert list(qs) == []

    def test_len(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert len(qs) == 0

    def test_bool(self):
        qs = GrpcFakeQuerySet(TestResource)
        assert bool(qs) is True


class TestModelWrapper:
    def test_getattr_delegates(self, fake_meta):
        instance = TestResource(id=1, name="Widget")
        wrapper = ModelWrapper(instance, fake_meta)
        assert wrapper.id == 1
        assert wrapper.name == "Widget"

    def test_fk_display_cache_hit(self, fake_meta):
        instance = TestResource(id=1, name="Widget")
        wrapper = ModelWrapper(instance, fake_meta, fk_display_cache={"category": "Books"})
        assert wrapper.category == "Books"

    def test_fk_display_cache_miss_uses_instance(self, fake_meta):
        instance = TestResource(id=1, name="Widget")
        wrapper = ModelWrapper(instance, fake_meta, fk_display_cache={"other": "value"})
        assert wrapper.name == "Widget"

    def test_fk_display_cache_no_instance_attr(self, fake_meta):
        instance = TestResource(id=1, name="Widget")
        wrapper = ModelWrapper(instance, fake_meta, fk_display_cache={"missing": "cached"})
        assert wrapper.missing == "cached"

    def test_meta_attribute(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert wrapper._meta is fake_meta

    def test_instance_attribute(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert wrapper._instance is instance

    def test_setattr_delegates(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        wrapper.name = "Updated"
        assert instance.name == "Updated"

    def test_str(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert str(wrapper) == "1"

    def test_repr(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert repr(wrapper) == repr(instance)

    def test_eq_same_instance(self, fake_meta):
        instance = TestResource(id=1)
        w1 = ModelWrapper(instance, fake_meta)
        w2 = ModelWrapper(instance, fake_meta)
        assert w1 == w2

    def test_eq_with_raw_instance(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert wrapper == instance

    def test_hash(self, fake_meta):
        instance = TestResource(id=1)
        wrapper = ModelWrapper(instance, fake_meta)
        assert hash(wrapper) == hash(instance)

    def test_hash_unhashable(self, fake_meta):
        class UnhashableResource(BaseGrpcResource):
            class Meta:
                app_label = "test"
                model_name = "unhashable"

            fields = [CharFieldConfig(name="data")]

        instance = UnhashableResource(data={"a": 1})
        wrapper = ModelWrapper(instance, fake_meta)
        # Should not raise
        h = hash(wrapper)
        assert isinstance(h, int)

    def test_serializable_value(self, fake_meta):
        instance = TestResource(id=1, name="Widget")
        wrapper = ModelWrapper(instance, fake_meta)
        assert wrapper.serializable_value("name") == "Widget"
        assert wrapper.serializable_value("missing") is None
