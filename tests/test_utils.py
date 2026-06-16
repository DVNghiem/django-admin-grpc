"""
Tests for django_admin_grpc.utils module.
"""

from collections.abc import Iterator

import pytest

from django_admin_grpc.utils import chunked


class TestChunked:
    def test_chunks_exact_multiple(self):
        result = list(chunked([1, 2, 3, 4, 5, 6], 2))
        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_chunks_with_remainder(self):
        result = list(chunked([1, 2, 3, 4, 5], 2))
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunk_size_one(self):
        result = list(chunked(["a", "b", "c"], 1))
        assert result == [["a"], ["b"], ["c"]]

    def test_chunk_larger_than_input(self):
        result = list(chunked([1, 2, 3], 10))
        assert result == [[1, 2, 3]]

    def test_empty_input(self):
        result = list(chunked([], 5))
        assert result == []

    def test_single_item(self):
        result = list(chunked(["only"], 5))
        assert result == [["only"]]

    def test_accepts_generators(self):
        def gen() -> Iterator[int]:
            yield from [1, 2, 3, 4, 5]

        result = list(chunked(gen(), 2))
        assert result == [[1, 2], [3, 4], [5]]

    def test_invalid_size_zero_raises(self):
        with pytest.raises(ValueError, match="chunk size must be >= 1"):
            list(chunked([1, 2, 3], 0))

    def test_invalid_size_negative_raises(self):
        with pytest.raises(ValueError, match="chunk size must be >= 1"):
            list(chunked([1, 2, 3], -1))

    def test_non_int_size_raises(self):
        with pytest.raises(TypeError, match="chunk size must be int"):
            list(chunked([1, 2, 3], 1.5))  # type: ignore[arg-type]

    def test_bool_size_raises(self):
        # ``True`` is technically int; ``False`` is too — but they make
        # no sense as chunk sizes.  The implementation explicitly rejects
        # bools to avoid the silent ``True == 1`` footgun.
        with pytest.raises(TypeError, match="chunk size must be int"):
            list(chunked([1, 2, 3], True))  # type: ignore[arg-type]
