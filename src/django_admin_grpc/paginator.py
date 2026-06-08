"""
Paginator and result types for gRPC-backed list views.
"""
from __future__ import annotations

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
