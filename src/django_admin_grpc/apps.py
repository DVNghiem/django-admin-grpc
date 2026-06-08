from django.apps import AppConfig


class DjangoGrpcAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_admin_grpc"
    verbose_name = "Django gRPC Admin"
    label = "django_admin_grpc"
