"""
Thread-safe gRPC channel pool with health checks and idle eviction.

The pool keeps up to *max_size* channels ready for a single target.  Channels
are created on demand and recycled.  A background daemon thread periodically
validates idle channels using ``channel_ready()`` and evicts any channel that
fails the check or has been idle longer than *max_idle_seconds*.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import grpc

from django_admin_grpc.settings import get_setting

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)


@dataclass
class _PooledChannel:
    """Internal wrapper tracking a pooled channel and its last-used time."""

    channel: grpc.Channel
    last_used: float = field(default_factory=time.monotonic)
    in_use: bool = False


class GrpcChannelPool:
    """
    A thread-safe pool of gRPC channels for a single target.

    Args:
        target: gRPC target string (e.g. ``"dns:///service:50051"``).
        min_size: Minimum number of channels to keep ready.
        max_size: Maximum number of channels that may exist at once.
        max_idle_seconds: Channels idle longer than this are eligible for
            eviction by the background health thread.
        health_check_interval_seconds: Seconds between background health passes.
        channel_factory: Optional callable ``(target) -> grpc.Channel`` used to
            create new channels.  Defaults to ``grpc.insecure_channel``.
        health_check_timeout_seconds: Timeout passed to ``channel_ready()``.
            Defaults to ``GRPC_ADMIN_POOL_HEALTH_CHECK_TIMEOUT`` setting.
    """

    def __init__(
        self,
        target: str,
        min_size: int | None = None,
        max_size: int | None = None,
        max_idle_seconds: float | None = None,
        health_check_interval_seconds: float | None = None,
        channel_factory: Callable[[str], grpc.Channel] | None = None,
        health_check_timeout_seconds: float | None = None,
    ) -> None:
        self.target = target
        self.min_size = self._resolve_setting(min_size, "GRPC_ADMIN_POOL_MIN_SIZE", int)
        self.max_size = self._resolve_setting(max_size, "GRPC_ADMIN_POOL_MAX_SIZE", int)
        self.max_idle_seconds = self._resolve_setting(
            max_idle_seconds, "GRPC_ADMIN_POOL_MAX_IDLE_SECONDS", float
        )
        self.health_check_interval_seconds = self._resolve_setting(
            health_check_interval_seconds, "GRPC_ADMIN_POOL_HEALTH_CHECK_INTERVAL", float
        )
        self.health_check_timeout_seconds = self._resolve_setting(
            health_check_timeout_seconds, "GRPC_ADMIN_POOL_HEALTH_CHECK_TIMEOUT", float
        )
        self.channel_factory = channel_factory or grpc.insecure_channel

        if self.min_size < 0:
            raise ValueError("min_size must be >= 0")
        if self.max_size < 1:
            raise ValueError("max_size must be >= 1")
        if self.min_size > self.max_size:
            raise ValueError("min_size cannot exceed max_size")
        if self.max_idle_seconds < 0:
            raise ValueError("max_idle_seconds must be >= 0")
        if self.health_check_interval_seconds <= 0:
            raise ValueError("health_check_interval_seconds must be > 0")

        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.max_size)
        self._pool: deque[_PooledChannel] = deque()
        self._evicted_total = 0
        self._closed = False
        self._health_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @staticmethod
    def _resolve_setting(value: Any, setting_name: str, caster: type) -> Any:
        """Return the provided value or the named Django setting coerced to *caster*."""
        if value is not None:
            return caster(value)
        return caster(get_setting(setting_name))

    def _start_health_thread(self) -> None:
        """Lazily start the background health-check thread."""
        with self._lock:
            if self._health_thread is not None and self._health_thread.is_alive():
                return
            if self._closed:
                return
            self._stop_event.clear()
            self._health_thread = threading.Thread(
                target=self._health_loop, daemon=True, name=f"grpc-pool-health-{self.target}"
            )
            self._health_thread.start()

    def _health_loop(self) -> None:
        """Daemon loop that evicts stale or unhealthy idle channels."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.health_check_interval_seconds)
            if self._stop_event.is_set():
                break
            try:
                self._evict_stale_or_unhealthy()
            except Exception:  # pragma: no cover
                logger.exception("Health check loop failed for target %s", self.target)

    def _evict_stale_or_unhealthy(self) -> None:
        """Evict idle channels that are stale or fail ``channel_ready()`` .

        Stale channels and channels that fail the health check have their
        semaphore permit released so the pool does not shrink over time.
        """
        if self._closed:
            return
        now = time.monotonic()

        # Work on a snapshot so the health check itself can be done outside
        # the lock.  Membership is re-verified before any mutation.
        with self._lock:
            snapshot = list(self._pool)

        for wrapper in snapshot:
            if wrapper.in_use:
                continue
            idle_for = now - wrapper.last_used
            if idle_for >= self.max_idle_seconds:
                self._evict_stale_idle(wrapper)
                continue

            # Reserve this slot while we check health so callers cannot
            # create extra channels beyond ``max_size``.
            self._semaphore.acquire()
            removed = False
            with self._lock:
                try:
                    self._pool.remove(wrapper)
                    removed = True
                except ValueError:
                    pass

            if not removed:
                self._semaphore.release()
                continue

            try:
                healthy = self._is_healthy(wrapper.channel)
            except Exception:
                healthy = False

            if healthy:
                with self._lock:
                    self._pool.append(wrapper)
                self._semaphore.release()
            else:
                self._close_channel(wrapper.channel)
                self._evicted_total += 1
                self._semaphore.release()
                logger.debug("Evicted unhealthy idle channel for %s", self.target)

        # Optionally warm up to min_size in the background.  This is best-effort;
        # failures are logged, not raised, because a caller will create a channel
        # on demand anyway.
        self._warm_min_channels()

    def _evict_stale_idle(self, wrapper: _PooledChannel) -> None:
        """Remove and close a stale idle channel, freeing its semaphore slot."""
        with self._lock:
            try:
                self._pool.remove(wrapper)
            except ValueError:
                return
            if wrapper.in_use:
                # It was checked out between snapshot and lock.
                self._pool.append(wrapper)
                return
            if (time.monotonic() - wrapper.last_used) < self.max_idle_seconds:
                # No longer stale; keep it.
                self._pool.append(wrapper)
                return
            self._semaphore.release()

        self._close_channel(wrapper.channel)
        self._evicted_total += 1
        logger.debug("Evicted stale idle channel for %s", self.target)

    def _warm_min_channels(self) -> None:
        """Create channels in the background until min_size idle exist."""
        if self._closed:
            return
        needed = self.min_size
        with self._lock:
            idle_count = sum(1 for w in self._pool if not w.in_use)
            needed = max(0, self.min_size - idle_count)

        for _ in range(needed):
            if self._closed:
                return
            acquired = self._semaphore.acquire(blocking=False)
            if not acquired:
                break
            try:
                channel = self._create_channel()
            except Exception:
                self._semaphore.release()
                logger.exception("Failed to warm channel for %s", self.target)
                break
            with self._lock:
                self._pool.append(_PooledChannel(channel=channel))

    def _create_channel(self) -> grpc.Channel:
        """Create a new channel using the configured factory."""
        return self.channel_factory(self.target)

    @staticmethod
    def _close_channel(channel: grpc.Channel) -> None:
        """Close a channel, logging any exception."""
        try:
            channel.close()
        except Exception:
            logger.exception("Error closing gRPC channel")

    def _is_healthy(self, channel: grpc.Channel) -> bool:
        """Return ``True`` if the channel becomes ready within the timeout."""
        try:
            grpc.channel_ready_future(channel).result(timeout=self.health_check_timeout_seconds)
            return True
        except Exception:
            return False

    def acquire(self) -> grpc.Channel:
        """
        Acquire a channel from the pool.

        Blocks until a channel is available if the pool is at *max_size* and all
        channels are currently checked out.
        """
        if self._closed:
            raise RuntimeError("GrpcChannelPool is closed")
        self._start_health_thread()
        self._semaphore.acquire()

        if self._closed:
            self._semaphore.release()
            raise RuntimeError("GrpcChannelPool is closed")

        try:
            with self._lock:
                for wrapper in self._pool:
                    if wrapper.in_use:
                        continue
                    wrapper.in_use = True
                    wrapper.last_used = time.monotonic()
                    return wrapper.channel

            # No idle channel available; create a new one while holding the
            # semaphore slot so total count remains bounded.
            channel = self._create_channel()
            with self._lock:
                if self._closed:
                    self._semaphore.release()
                    self._close_channel(channel)
                    raise RuntimeError("GrpcChannelPool is closed")
                wrapper = _PooledChannel(channel=channel, last_used=time.monotonic(), in_use=True)
                self._pool.append(wrapper)
            return channel
        except Exception:
            self._semaphore.release()
            raise

    def release(self, channel: grpc.Channel) -> None:
        """Return a previously acquired channel to the pool."""
        with self._lock:
            for wrapper in self._pool:
                if wrapper.channel is channel:
                    if not wrapper.in_use:
                        logger.warning("Channel released twice to pool for %s", self.target)
                        return
                    wrapper.in_use = False
                    wrapper.last_used = time.monotonic()
                    self._semaphore.release()
                    return

        # Channel not tracked. During shutdown the pool may have been cleared
        # while the channel was in use; close it without touching the semaphore
        # because ``close_all`` already released enough permits to unblock
        # waiters.
        self._close_channel(channel)

    @contextmanager
    def get_channel(self) -> Generator[grpc.Channel, None, None]:
        """Context manager that acquires and releases a channel."""
        channel = self.acquire()
        try:
            yield channel
        finally:
            self.release(channel)

    def metrics(self) -> dict[str, int]:
        """Return current pool metrics."""
        with self._lock:
            idle = sum(1 for w in self._pool if not w.in_use)
            in_use = sum(1 for w in self._pool if w.in_use)
            return {
                "pool_size": len(self._pool),
                "idle": idle,
                "in_use": in_use,
                "evicted_total": self._evicted_total,
            }

    def close_all(self) -> None:
        """Stop the health thread and close every pooled channel."""
        with self._lock:
            self._closed = True
            self._stop_event.set()
            channels = [w.channel for w in self._pool]
            self._pool.clear()

        # Unblock any threads waiting on the semaphore.
        for _ in range(self.max_size):
            self._semaphore.release()

        for channel in channels:
            self._close_channel(channel)

        thread = self._health_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._health_thread = None

    def __enter__(self) -> GrpcChannelPool:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close_all()
