"""
Tests for django_admin_grpc.paginator module.
"""

from django_admin_grpc.paginator import GrpcPaginator, PagedResult, compute_filter_fingerprint


class TestPagedResult:
    def test_defaults(self):
        result = PagedResult(items=[])
        assert result.items == []
        assert result.total == 0
        assert result.page == 1
        assert result.page_size == 25
        assert result.next_cursor is None

    def test_full_init(self):
        result = PagedResult(
            items=[1, 2, 3],
            total=100,
            page=2,
            page_size=50,
            next_cursor="abc123",
        )
        assert result.items == [1, 2, 3]
        assert result.total == 100
        assert result.page == 2
        assert result.page_size == 50
        assert result.next_cursor == "abc123"


class TestGrpcPaginator:
    def test_count_property(self):
        paginator = GrpcPaginator(["a", "b", "c"], per_page=10, total_count=100)
        assert paginator.count == 100

    def test_count_overrides_object_list_length(self):
        paginator = GrpcPaginator(["a", "b"], per_page=10, total_count=500)
        assert paginator.count == 500
        assert len(paginator.object_list) == 2

    def test_page(self):
        items = list(range(25))
        paginator = GrpcPaginator(items, per_page=10, total_count=100)
        page = paginator.page(1)
        assert len(page.object_list) == 10  # paginator slices to per_page
        assert paginator.count == 100

    def test_empty_list(self):
        paginator = GrpcPaginator([], per_page=25, total_count=0)
        assert paginator.count == 0
        page = paginator.page(1)
        assert len(page.object_list) == 0


class TestComputeFilterFingerprint:
    def test_deterministic_by_key_order(self):
        fp1 = compute_filter_fingerprint({"a": 1, "b": 2})
        fp2 = compute_filter_fingerprint({"b": 2, "a": 1})
        assert fp1 == fp2

    def test_value_changes_differ(self):
        fp1 = compute_filter_fingerprint({"a": 1})
        fp2 = compute_filter_fingerprint({"a": 2})
        assert fp1 != fp2

    def test_length(self):
        fp = compute_filter_fingerprint({"a": 1, "b": 2})
        assert len(fp) == 16
