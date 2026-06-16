# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - Unreleased

### Added

- Batch operations on `BaseGrpcServiceAdapter` and `BaseAsyncGrpcServiceAdapter`:
  - `bulk_create(resource_class, items, batch_size=None)` — chunked fallback
    that loops `create()`; the resource class is the first positional argument
    so the call is unambiguous.
  - `bulk_update(resource_class, items, batch_size=None)` — chunked fallback
    that loops `update()`; the primary-key field is discovered from
    `resource_class.Meta.pk_field`.
  - `bulk_delete(resource_class, pks, batch_size=None)` — chunked fallback
    that loops `delete()`.
  - All three honour `self.batch_size` (default 100) and an explicit `batch_size`
    override; on partial failure they raise `GrpcBatchPartialError` with the
    succeeded and failed entries; on full success `bulk_delete` returns
    `{"deleted": <int>, "failed": []}`.  Per-failure log entries record only
    the resource name, the PK (or item index for `bulk_create`), and the
    exception message — raw input payloads are intentionally not logged
    because they may contain sensitive fields.
- New `GrpcBatchPartialError` exception in `django_admin_grpc.exceptions` with
  `succeeded`, `failed`, and `operation` attributes for granular partial-failure
  handling.
- New `BulkActionMixin` in `django_admin_grpc.admin`:
  - `GrpcResourceAdmin` now inherits from it.
  - `bulk_delete_action` is automatically registered in the changelist actions
    dropdown when deletion is enabled, replacing Django's default
    `delete_selected` (the legacy `grpc_delete_selected` alias remains for
    backward compatibility).
  - Opt-in `bulk_create_action` and `bulk_update_action` are exposed when
    `grpc_bulk_create_enabled = True` / `grpc_bulk_update_enabled = True` are
    set on the admin.
  - `apply_grpc_bulk_delete` helper centralises the chunked delete flow and
    reports failures through Django messages + `GrpcBatchPartialError`. The
    helper catches `GrpcBatchPartialError` internally; partial failures are
    surfaced as Django messages and a `None` return value, not by re-raising
    the exception.
- The opt-in `bulk_create_action` and `bulk_update_action` route through
  `run_async(...)` when the resolved adapter is a
  `BaseAsyncGrpcServiceAdapter`, mirroring the async handling used by
  `apply_grpc_bulk_delete` so async adapters do not receive an un-awaited
  coroutine.
- New `@bulk_grpc_action(description, field, value)` decorator that turns a
  method into a single-field bulk update action; works with both parenthesised
  and bare invocations.
- New `utils.py` exposing the pure-Python `chunked(iterable, size)` helper used
  by the bulk operations.
- New `cache.py` module with `GrpcAdminCache` and `CachedAdapterMixin`:
  - Reads defaults from Django settings: `GRPC_ADMIN_CACHE_ENABLED`,
    `GRPC_ADMIN_CACHE_TTL`, `GRPC_ADMIN_CACHE_PREFIX`,
    `GRPC_ADMIN_CACHE_BACKEND`.
  - Stable SHA-256 keys derived from sorted JSON kwargs, namespaced by resource
    and operation.
  - Caches `list()` / `get()` reads; invalidates the resource namespace on
    `create()`, `update()`, `delete()`, `bulk_create()`, `bulk_update()`, and
    `bulk_delete()` when the mixin is in the adapter MRO.
  - When `grpc_cache` is `None` or caching is disabled globally, the mixin
    passes through to the base adapter unchanged.

## [0.4.0] - Unreleased

### Added

- Channel pooling with health check via `GrpcChannelPool`
- Async adapter support via `BaseAsyncGrpcServiceAdapter` and `AsyncAdapterRegistry`
- `AsyncGrpcResourceAdmin` with async-aware adapter hooks (`_adapter_get`,
  `_adapter_create`, `_adapter_update`, `_adapter_delete`) that route through
  `run_async` for `BaseAsyncGrpcServiceAdapter` instances
- `grpc_action` decorator accepts a list of selected PKs for gRPC bulk operations

### Fixed

- `apply_grpc_bulk_update` and `_grpc_delete_selected` now route through
  `self._adapter_update` / `self._adapter_delete`, so `AsyncGrpcResourceAdmin`
  correctly awaits the coroutine instead of receiving an un-awaited value
- FK display resolution falls back to `AsyncAdapterRegistry` for async-only
  related services and routes async `get` / `batch_get` calls through the
  async bridge

## [0.2.2] - 2024-XX-XX

### Added

- Initial release with `BaseGrpcResource`, `BaseGrpcServiceAdapter`, `GrpcResourceAdmin`, and `AdapterRegistry`.
