# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
