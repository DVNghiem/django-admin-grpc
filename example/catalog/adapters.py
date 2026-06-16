"""
In-memory gRPC adapters for the Catalog example.

These adapters simulate a real gRPC service using simple Python dicts so the
example runs without any external server.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django_admin_grpc.adapters import BaseGrpcServiceAdapter
from django_admin_grpc.paginator import PagedResult

from .resources import CategoryResource, ProductResource

logger = logging.getLogger(__name__)


class CatalogGrpcAdapter(BaseGrpcServiceAdapter):
    """
    In-memory adapter that mimics a Catalog gRPC microservice.

    Stores products and categories in plain dicts so the example works
    out-of-the-box without a running gRPC server.
    """

    service_name = "catalog"

    # Shared in-memory "database"
    _categories: dict[str, dict[str, Any]] = {}
    _products: dict[str, dict[str, Any]] = {}
    _seeded: bool = False

    def __init__(self) -> None:
        if not CatalogGrpcAdapter._seeded:
            CatalogGrpcAdapter._seed_data()

    @classmethod
    def _seed_data(cls) -> None:
        """Populate the store with demo data."""
        if cls._seeded:
            return

        categories = [
            {
                "id": "cat-1",
                "name": "Electronics",
                "description": "Gadgets and devices",
                "active": True,
            },
            {
                "id": "cat-2",
                "name": "Books",
                "description": "Physical and digital books",
                "active": True,
            },
            {
                "id": "cat-3",
                "name": "Clothing",
                "description": "Apparel and accessories",
                "active": False,
            },
        ]
        for c in categories:
            cls._categories[c["id"]] = c

        products = [
            {
                "id": "prod-1",
                "sku": "WH-001",
                "name": "Wireless Headphones",
                "description": "Noise-cancelling over-ear",
                "price": 199.99,
                "active": True,
                "category_id": "cat-1",
                "rating": 5,
                "release_date": "2023-09-01",
                "product_type": "physical",
                "notes": "Top seller",
                "badge": "Bestseller",
            },
            {
                "id": "prod-2",
                "sku": "BK-001",
                "name": "Python Cookbook",
                "description": "Recipes for mastering Python",
                "price": 39.99,
                "active": True,
                "category_id": "cat-2",
                "rating": 4,
                "release_date": "2022-05-15",
                "product_type": "digital",
                "notes": "Editor's pick",
                "badge": "Editor's Choice",
            },
            {
                "id": "prod-3",
                "sku": "CL-001",
                "name": "Cotton T-Shirt",
                "description": "Comfortable everyday wear",
                "price": 24.99,
                "active": True,
                "category_id": "cat-3",
                "rating": 3,
                "release_date": "2021-03-10",
                "product_type": "physical",
                "notes": "Seasonal item",
                "badge": "",
            },
            {
                "id": "prod-4",
                "sku": "SW-001",
                "name": "Smart Watch",
                "description": "Fitness tracking and notifications",
                "price": 299.99,
                "active": True,
                "category_id": "cat-1",
                "rating": 5,
                "release_date": "2023-11-20",
                "product_type": "physical",
                "notes": "New arrival",
                "badge": "New",
            },
            {
                "id": "prod-5",
                "sku": "SF-001",
                "name": "Sci-Fi Anthology",
                "description": "Best of 2024",
                "price": 15.99,
                "active": False,
                "category_id": "cat-2",
                "rating": 4,
                "release_date": "2024-01-10",
                "product_type": "digital",
                "notes": "Pre-order",
                "badge": "",
            },
            {
                "id": "prod-6",
                "sku": "XX-001",
                "name": "Mystery Item",
                "description": "Unknown origin",
                "price": 9.99,
                "active": True,
                "category_id": "unknown-cat",
                "rating": 2,
                "release_date": "2020-01-01",
                "product_type": "service",
                "notes": "Uncategorized",
                "badge": "",
            },
        ]
        for p in products:
            cls._products[p["id"]] = p

        cls._seeded = True

    # ── Adapter interface ──────────────────────────────────────────────────

    def list(
        self,
        resource_class: type[Any],
        page: int = 1,
        page_size: int = 25,
        filters: dict[str, Any] | None = None,
    ) -> PagedResult:
        filters = filters or {}
        store = self._get_store(resource_class)
        items = list(store.values())

        # In-memory filtering
        search = filters.get("search", "").lower()
        if search:
            items = [
                item for item in items if any(search in str(item.get(k, "")).lower() for k in item)
            ]

        for key, value in filters.items():
            if key in ("search", "cursor"):
                continue

            if key.endswith("__gte"):
                field = key[:-5]
                casted = self._cast_for_field(field, value)
                items = [
                    item
                    for item in items
                    if item.get(field) is not None and item.get(field) >= casted
                ]
            elif key.endswith("__lte"):
                field = key[:-5]
                casted = self._cast_for_field(field, value)
                items = [
                    item
                    for item in items
                    if item.get(field) is not None and item.get(field) <= casted
                ]
            elif key.endswith("__gt"):
                field = key[:-4]
                casted = self._cast_for_field(field, value)
                items = [
                    item
                    for item in items
                    if item.get(field) is not None and item.get(field) > casted
                ]
            elif key.endswith("__lt"):
                field = key[:-4]
                casted = self._cast_for_field(field, value)
                items = [
                    item
                    for item in items
                    if item.get(field) is not None and item.get(field) < casted
                ]
            elif key.endswith("__in"):
                field = key[:-4]
                vals = (
                    value
                    if isinstance(value, list)
                    else [v.strip() for v in str(value).split(",") if v.strip()]
                )
                items = [item for item in items if str(item.get(field, "")) in vals]
            else:
                items = [item for item in items if str(item.get(key, "")) == str(value)]

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        instances = [resource_class(**item) for item in page_items]
        return PagedResult(
            items=instances,
            total=total,
            page=page,
            page_size=page_size,
        )

    def get(self, resource_class: type[Any], pk: str) -> Any | None:
        store = self._get_store(resource_class)
        data = store.get(str(pk))
        if data is None:
            return None
        return resource_class(**data)

    def create(self, resource_class: type[Any], data: dict[str, Any]) -> Any:
        store = self._get_store(resource_class)
        pk = str(uuid.uuid4())[:8]
        record = dict(data)
        record["id"] = pk
        store[pk] = record
        return resource_class(**record)

    def update(self, resource_class: type[Any], pk: str, data: dict[str, Any]) -> Any:
        store = self._get_store(resource_class)
        record = store.get(str(pk))
        if record is None:
            raise RuntimeError(f"{resource_class.__name__} with id={pk} not found")
        record.update({k: v for k, v in data.items() if v is not None})
        return resource_class(**record)

    def delete(self, resource_class: type[Any], pk: str) -> bool:
        store = self._get_store(resource_class)
        if str(pk) in store:
            del store[str(pk)]
            return True
        return False

    # ── Helpers ────────────────────────────────────────────────────────────

    def get_category(self, resource_class: type[Any], pk: str) -> CategoryResource | None:
        """Fetch a single category by ID (used for FK resolution)."""
        data = CatalogGrpcAdapter._categories.get(str(pk))
        if data is None:
            return None
        return CategoryResource(**data)

    def _get_store(self, resource_class: type[Any]) -> dict[str, dict[str, Any]]:
        if resource_class is CategoryResource:
            return CatalogGrpcAdapter._categories
        if resource_class is ProductResource:
            return CatalogGrpcAdapter._products
        raise ValueError(f"Unknown resource class: {resource_class}")

    @staticmethod
    def _cast_for_field(field: str, raw: str) -> Any:
        """Cast filter value to the appropriate Python type."""
        if field == "price":
            return float(raw)
        if field == "rating":
            return int(raw)
        return raw


class CategoryAdapter(CatalogGrpcAdapter):
    """Convenience alias for registering the category service separately."""

    service_name = "catalog_category"
