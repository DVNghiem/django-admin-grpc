# Changelog

All notable changes to this project will be documented in this file.

## 0.3.0

### Added

- New typed exceptions for additional gRPC status codes:
  - `GrpcAlreadyExistsError`
  - `GrpcResourceExhaustedError`
  - `GrpcFailedPreconditionError`
  - `GrpcAbortedError`
  - `GrpcCancelledError`
- `map_grpc_error` now maps `ALREADY_EXISTS`, `RESOURCE_EXHAUSTED`, `FAILED_PRECONDITION`, `ABORTED`, and `CANCELLED` to their respective exception subclasses.
- Admin message rendering helpers that convert gRPC exceptions into Django messages with sensible levels and text.
- `BaseGrpcServiceAdapter.batch_get` optional helper for bulk FK lookups with a fallback implementation that loops `get()`.
- FK N+1 prevention in changelist rendering: distinct FK values for service-backed `FKFieldConfig` fields are collected per page and resolved with a single `batch_get` call.
- `ModelWrapper` now supports an optional `fk_display_cache` that is consulted before delegating attribute access to the wrapped instance.
- `BaseGrpcServiceAdapter._create_channel` lifecycle helper that creates a raw gRPC channel, wraps it with the trace interceptor, and closes the raw channel if wrapping fails.
- `BaseGrpcServiceAdapter.close` now closes `self._channel` when present.
- `AdapterRegistry.close_all` closes every registered adapter's channel.
- `AdapterRegistry.freeze` makes the registry read-only; `register`/`unregister` raise `RuntimeError` after freezing, while `get_adapter` remains lock-free.
- `AdapterRegistry` register/unregister/get operations are protected by `threading.RLock` before freeze.
- `compute_filter_fingerprint` in `paginator.py` produces a stable SHA-256-based fingerprint for filter dictionaries.
- Cursor pagination now includes a `__grpc_filter_fp` query parameter in next-cursor URLs and resets the cursor when the incoming `__grpc_filter_fp` does not match the currently applied filters.
- `resolve_source_path` supports dot-separated attribute/dict lookup for nested response fields.
- `BaseGrpcResource.from_response` now resolves nested `source` paths while preserving exact single-segment behavior.

### Fixed

- gRPC channels are now closed reliably through `close()` and `AdapterRegistry.close_all()`.
- Cursor pagination no longer carries stale cursors across filter changes.
