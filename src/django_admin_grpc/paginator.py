"""
Paginator and result types for gRPC-backed list views.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.core.paginator import Paginator


@dataclass
class PagedResult:
    """
    Standard shape returned by an adapter's ``list()`` method.

    Attributes:
        items: The page of resource instances.
        total: Total number of items across all pages (for offset pagination).
        page: Current page number (1-indexed).
        page_size: Number of items per page.
        next_cursor: Opaque cursor string for cursor-based pagination.
    """

    items: list[Any]
    total: int = 0
    page: int = 1
    page_size: int = 25
    next_cursor: str | None = None


def compute_filter_fingerprint(filters: dict[str, Any]) -> str:
    """
    Return a short stable fingerprint for *filters*.

    The fingerprint is deterministic regardless of key insertion order because
    the dictionary is serialized as JSON with sorted keys.

    Args:
        filters: A filter dictionary (values should be JSON-serializable).

    Returns:
        A short SHA-256 hex prefix that uniquely identifies the filter set.
    """
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class GrpcPaginator(Paginator):
    """
    A paginator that uses a pre-computed total count from the gRPC service.
    """

    def __init__(
        self,
        object_list: list[Any],
        per_page: int,
        total_count: int,
        **kwargs: Any,
    ):
        super().__init__(object_list, per_page, **kwargs)
        self._total_count = total_count

    @property
    def count(self) -> int:
        return self._total_count
