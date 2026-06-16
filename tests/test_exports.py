"""
Smoke test for the top-level ``django_admin_grpc`` public API.

Verifies that the symbols listed in the package ``__all__`` are actually
importable from the package root.  This guards against accidental
removals during refactors.
"""

import django_admin_grpc


class TestTopLevelExports:
    def test_bulk_action_mixin_exported(self):
        assert hasattr(django_admin_grpc, "BulkActionMixin")
        assert django_admin_grpc.BulkActionMixin is not None

    def test_bulk_grpc_action_exported(self):
        assert hasattr(django_admin_grpc, "bulk_grpc_action")
        assert callable(django_admin_grpc.bulk_grpc_action)

    def test_grpc_admin_cache_exported(self):
        assert hasattr(django_admin_grpc, "GrpcAdminCache")
        from django_admin_grpc.cache import GrpcAdminCache

        assert django_admin_grpc.GrpcAdminCache is GrpcAdminCache

    def test_cached_adapter_mixin_exported(self):
        assert hasattr(django_admin_grpc, "CachedAdapterMixin")
        from django_admin_grpc.cache import CachedAdapterMixin

        assert django_admin_grpc.CachedAdapterMixin is CachedAdapterMixin

    def test_grpc_batch_partial_error_exported(self):
        assert hasattr(django_admin_grpc, "GrpcBatchPartialError")
        from django_admin_grpc.exceptions import GrpcBatchPartialError

        assert django_admin_grpc.GrpcBatchPartialError is GrpcBatchPartialError

    def test_chunked_exported(self):
        assert hasattr(django_admin_grpc, "chunked")
        from django_admin_grpc.utils import chunked

        assert django_admin_grpc.chunked is chunked

    def test_all_list_matches_actual_attributes(self):
        """Every name in ``__all__`` must resolve on the package."""
        for name in django_admin_grpc.__all__:
            assert hasattr(django_admin_grpc, name), (
                f"django_admin_grpc.__all__ lists {name!r} but the package does not expose it"
            )
