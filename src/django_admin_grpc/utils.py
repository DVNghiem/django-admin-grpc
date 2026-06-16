"""
Generic pure-Python utilities for django-admin-grpc.

Currently exposes a single, dependency-free ``chunked`` helper used by the
adapter bulk operations.  New utilities that are not part of the public gRPC
contract (resource, admin, adapter, exception) belong here.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable
from typing import TypeVar

T = TypeVar("T")

__all__ = ["chunked"]


def chunked[T](iterable: Iterable[T], size: int) -> Generator[list[T], None, None]:
    """
    Yield successive ``size``-element chunks from *iterable* as lists.

    The final chunk may be shorter than *size* if the input is not divisible.
    *size* must be a positive integer.

    Args:
        iterable: Any finite iterable.
        size: Maximum number of elements per chunk (must be >= 1).

    Yields:
        Lists containing at most *size* items each.

    Raises:
        TypeError: If *size* is not an integer.
        ValueError: If *size* is less than 1.
    """
    if not isinstance(size, int) or isinstance(size, bool):
        raise TypeError(f"chunk size must be int, got {type(size).__name__}")
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")

    chunk: list[T] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
