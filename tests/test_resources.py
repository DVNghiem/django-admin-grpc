"""
Tests for django_admin_grpc.resources module.
"""
from django import forms

from django_admin_grpc.resources import (
    BaseGrpcResource,
    BooleanFieldConfig,
    CharFieldConfig,
    ChoicesFieldConfig,
    DateFieldConfig,
    DateTimeFieldConfig,
    FKFieldConfig,
    FloatFieldConfig,
    IntegerFieldConfig,
    TextFieldConfig,
)


class TestCharFieldConfig:
    def test_defaults(self):
        fc = CharFieldConfig(name="title")
        assert fc.name == "title"
        assert fc.type == "char"
        assert fc.label == "Title"
        assert fc.required is True
        assert fc.help_text == ""
        assert fc.max_length is None

    def test_label_override(self):
        fc = CharFieldConfig(name="first_name", label="First Name")
        assert fc.label == "First Name"

    def test_post_init_label_generation(self):
        fc = CharFieldConfig(name="created_at")
        assert fc.label == "Created At"

    def test_full_config(self):
        fc = CharFieldConfig(
            name="status",
            label="Status",
            required=False,
            help_text="Current status",
            initial="pending",
            max_length=20,
            readonly=True,
            detail_only=True,
        )
        assert fc.initial == "pending"
        assert fc.max_length == 20
        assert fc.readonly is True
        assert fc.editable is True
        assert fc.detail_only is True
        assert fc.list_only is False


class TestChoicesFieldConfig:
    def test_defaults(self):
        fc = ChoicesFieldConfig(name="status")
        assert fc.type == "choices"
        assert fc.choices == []

    def test_with_choices(self):
        fc = ChoicesFieldConfig(
            name="status",
            choices=[("pending", "Pending"), ("done", "Done")],
        )
        assert fc.choices == [("pending", "Pending"), ("done", "Done")]


class TestFKFieldConfig:
    def test_defaults(self):
        fc = FKFieldConfig(name="category_id")
        assert fc.type == "fk"
        assert fc.model is None
        assert fc.get_method == "get"

    def test_full_config(self):
        fc = FKFieldConfig(
            name="category_id",
            model="auth.User",
            to_field="id",
            display_field="username",
            service="users",
            get_method="get_user",
        )
        assert fc.model == "auth.User"
        assert fc.display_field == "username"
        assert fc.service == "users"


class TestOtherFieldConfigs:
    def test_text_field_config(self):
        fc = TextFieldConfig(name="description")
        assert fc.type == "text"

    def test_integer_field_config(self):
        fc = IntegerFieldConfig(name="count")
        assert fc.type == "integer"

    def test_float_field_config(self):
        fc = FloatFieldConfig(name="price")
        assert fc.type == "float"

    def test_boolean_field_config(self):
        fc = BooleanFieldConfig(name="active")
        assert fc.type == "boolean"

    def test_datetime_field_config(self):
        fc = DateTimeFieldConfig(name="created_at")
        assert fc.type == "datetime"

    def test_date_field_config(self):
        fc = DateFieldConfig(name="birth_date")
        assert fc.type == "date"


class ProductResource(BaseGrpcResource):
    class Meta:
        app_label = "shop"
        model_name = "product"
        verbose_name = "Product"
        verbose_name_plural = "Products"
        pk_field = "sku"

    fields = [
        CharFieldConfig(name="sku", label="SKU"),
        CharFieldConfig(name="name"),
        FloatFieldConfig(name="price"),
        BooleanFieldConfig(name="active"),
        FKFieldConfig(name="category_id", model="auth.User"),
    ]


class TestBaseGrpcResource:
    def test_instance_creation(self):
        p = ProductResource(sku="ABC123", name="Widget", price=9.99, active=True)
        assert p.sku == "ABC123"
        assert p.name == "Widget"
        assert p.price == 9.99
        assert p.active is True
        assert p.category_id is None

    def test_pk_property(self):
        p = ProductResource(sku="ABC123", name="Widget")
        assert p.pk == "ABC123"

    def test_str(self):
        p = ProductResource(sku="ABC123")
        assert str(p) == "ABC123"

    def test_get_field_configs(self):
        configs = ProductResource.get_field_configs()
        assert len(configs) == 5
        assert configs[0].name == "sku"

    def test_get_field_names(self):
        names = ProductResource.get_field_names()
        assert names == ["sku", "name", "price", "active", "category_id"]

    def test_get_field_config_found(self):
        fc = ProductResource.get_field_config("price")
        assert fc is not None
        assert isinstance(fc, FloatFieldConfig)
        assert fc.type == "float"

    def test_get_field_config_not_found(self):
        fc = ProductResource.get_field_config("nonexistent")
        assert fc is None

    def test_from_response_with_dict(self):
        response = {"sku": "XYZ", "name": "Gadget", "price": 19.99, "active": False}
        p = ProductResource.from_response(response)
        assert p.sku == "XYZ"
        assert p.name == "Gadget"
        assert p.price == 19.99
        assert p.active is False

    def test_from_response_with_object(self):
        class Resp:
            sku = "OBJ001"
            name = "Object"
            price = 5.0
            active = True
            category_id = None

        p = ProductResource.from_response(Resp())
        assert p.sku == "OBJ001"
        assert p.name == "Object"

    def test_from_response_missing_attribute(self):
        class Resp:
            sku = "PARTIAL"

        p = ProductResource.from_response(Resp())
        assert p.sku == "PARTIAL"
        assert p.name is None
        assert p.price is None

    def test_from_response_with_source(self):
        class PriceResource(BaseGrpcResource):
            class Meta:
                app_label = "test"
                model_name = "price"

            fields = [
                FloatFieldConfig(name="amount", source="value"),
            ]

        p = PriceResource.from_response({"value": 99.99})
        assert p.amount == 99.99

    def test_admin_model(self):
        fake_model = ProductResource.admin_model()
        assert fake_model.__name__ == "ProductResource"
        meta = fake_model._meta
        assert meta.app_label == "shop"
        assert meta.model_name == "product"
        assert meta.verbose_name == "Product"
        assert meta.verbose_name_plural == "Products"
        assert hasattr(fake_model, "objects")
        assert hasattr(fake_model, "DoesNotExist")
        assert hasattr(fake_model, "MultipleObjectsReturned")

    def test_admin_model_defaults(self):
        class MinimalResource(BaseGrpcResource):
            class Meta:
                pass

            fields = [CharFieldConfig(name="id")]

        fake_model = MinimalResource.admin_model()
        meta = fake_model._meta
        assert meta.app_label == "grpc_admin"
        assert meta.model_name == "minimalresource"
        assert meta.verbose_name == "Minimalresource"
        assert meta.verbose_name_plural == "Minimalresources"

    def test_build_form_class(self):
        form_class = ProductResource.build_form_class()
        assert issubclass(form_class, forms.Form)
        assert "sku" in form_class.base_fields
        assert "name" in form_class.base_fields
        assert "price" in form_class.base_fields
        assert "active" in form_class.base_fields

    def test_build_form_class_with_widgets(self):
        form_class = ProductResource.build_form_class(
            widgets={"name": forms.Textarea()}
        )
        assert isinstance(form_class.base_fields["name"].widget, forms.Textarea)
