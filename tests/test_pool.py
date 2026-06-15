"""
Tests for django_admin_grpc.pool module.
"""

import threading
import time
from unittest.mock import MagicMock, Mock, patch

import grpc
import pytest

from django_admin_grpc.pool import GrpcChannelPool, _PooledChannel


def make_channel(ready: bool = True) -> MagicMock:
    """Return a mock channel that satisfies ``grpc.channel_ready_future``."""
    channel = MagicMock(spec=grpc.Channel)
    return channel


def channel_factory(target: str) -> MagicMock:
    """Factory matching the ``(target) -> grpc.Channel`` signature."""
    return make_channel()


def patch_channel_ready_future(ready: bool = True):
    """Patch ``grpc.channel_ready_future`` to return a future with the given result."""
    future = Mock()
    future.result = Mock(
        side_effect=None
        if ready
        else (lambda timeout=None: (_ for _ in ()).throw(grpc.FutureTimeoutError("not ready")))
    )
    return patch("django_admin_grpc.pool.grpc.channel_ready_future", return_value=future)


class TestGrpcChannelPoolInit:
    def test_uses_provided_kwargs(self):
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=1,
            max_size=5,
            max_idle_seconds=60.0,
            health_check_interval_seconds=10.0,
            health_check_timeout_seconds=1.0,
        )
        assert pool.min_size == 1
        assert pool.max_size == 5
        assert pool.max_idle_seconds == 60.0
        assert pool.health_check_interval_seconds == 10.0
        assert pool.health_check_timeout_seconds == 1.0

    def test_uses_settings_defaults(self):
        pool = GrpcChannelPool("svc:50051")
        assert pool.min_size == 2
        assert pool.max_size == 10
        assert pool.max_idle_seconds == 300.0
        assert pool.health_check_interval_seconds == 30.0
        assert pool.health_check_timeout_seconds == 2.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"min_size": -1},
            {"max_size": 0},
            {"min_size": 5, "max_size": 2},
            {"max_idle_seconds": -1.0},
            {"health_check_interval_seconds": 0.0},
        ],
    )
    def test_validation(self, kwargs):
        with pytest.raises(ValueError):
            GrpcChannelPool("svc:50051", **kwargs)


class TestGrpcChannelPoolAcquireRelease:
    def test_acquire_creates_channel_when_pool_empty(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=2, channel_factory=factory)

        with pool.get_channel() as channel:
            assert channel is factory.return_value
            assert pool.metrics()["in_use"] == 1

        assert pool.metrics()["idle"] == 1
        factory.assert_called_once_with("svc:50051")
        pool.close_all()

    def test_acquire_reuses_idle_channel(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=2, channel_factory=factory)

        with pool.get_channel():
            pass
        with pool.get_channel() as channel2:
            assert channel2 is factory.return_value

        assert factory.call_count == 1
        pool.close_all()

    def test_blocks_when_at_max_size(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1, channel_factory=factory)

        acquired_event = threading.Event()
        released_event = threading.Event()
        result_channel = None

        def holder() -> None:
            nonlocal result_channel
            with pool.get_channel() as channel:
                result_channel = channel
                acquired_event.set()
                released_event.wait()

        thread = threading.Thread(target=holder)
        thread.start()
        acquired_event.wait(timeout=1)

        # Second acquire should block until the first is released.
        acquired2 = threading.Event()
        result_channel2 = None

        def waiter() -> None:
            nonlocal result_channel2
            with pool.get_channel() as channel:
                result_channel2 = channel
                acquired2.set()

        thread2 = threading.Thread(target=waiter)
        thread2.start()
        time.sleep(0.05)
        assert not acquired2.is_set()

        released_event.set()
        thread.join(timeout=1)
        acquired2.wait(timeout=1)
        thread2.join(timeout=1)

        assert result_channel2 is factory.return_value
        pool.close_all()

    def test_release_unknown_channel_closes_it(self):
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1)
        unknown = make_channel()
        pool.release(unknown)
        unknown.close.assert_called_once()
        pool.close_all()

    def test_double_release_is_no_op(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=2, channel_factory=factory)
        channel = pool.acquire()
        pool.release(channel)
        pool.release(channel)
        assert pool.metrics()["idle"] == 1
        pool.close_all()

    def test_acquire_after_close_raises(self):
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1)
        pool.close_all()
        with pytest.raises(RuntimeError, match="closed"):
            pool.acquire()


class TestGrpcChannelPoolHealth:
    def test_health_thread_evicts_stale_channels(self):
        channel = make_channel()
        factory = Mock(return_value=channel)
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=0,
            max_size=2,
            max_idle_seconds=0.05,
            health_check_interval_seconds=0.05,
            channel_factory=factory,
        )

        with pool.get_channel():
            pass

        # Health thread starts lazily on acquire.
        assert pool._health_thread is not None

        # Wait for the background thread to evict the idle channel.
        for _ in range(50):
            if pool.metrics()["evicted_total"] > 0:
                break
            time.sleep(0.01)

        pool.close_all()
        assert pool.metrics()["evicted_total"] == 1
        channel.close.assert_called_once()

    def test_health_check_skips_in_use_channels(self):
        channel = make_channel()
        factory = Mock(return_value=channel)
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=0,
            max_size=2,
            max_idle_seconds=0.05,
            health_check_interval_seconds=0.05,
            channel_factory=factory,
        )

        acquired = pool.acquire()
        time.sleep(0.15)
        metrics = pool.metrics()
        assert metrics["in_use"] == 1
        assert metrics["evicted_total"] == 0
        pool.release(acquired)
        pool.close_all()

    def test_is_healthy_false_on_timeout(self):
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1)
        channel = make_channel()
        with patch_channel_ready_future(ready=False):
            assert pool._is_healthy(channel) is False

    def test_is_healthy_true_when_ready(self):
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1)
        channel = make_channel()
        with patch_channel_ready_future(ready=True):
            assert pool._is_healthy(channel) is True

    def test_health_check_evicts_unhealthy_idle_channels(self):
        channel = make_channel()
        factory = Mock(return_value=channel)
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=0,
            max_size=2,
            max_idle_seconds=60.0,
            health_check_interval_seconds=0.05,
            channel_factory=factory,
        )

        with pool.get_channel():
            pass

        with patch_channel_ready_future(ready=False):
            for _ in range(50):
                if pool.metrics()["evicted_total"] > 0:
                    break
                time.sleep(0.01)

        pool.close_all()
        assert pool.metrics()["evicted_total"] == 1
        channel.close.assert_called_once()

    def test_eviction_releases_semaphore_permit(self):
        """A channel evicted by the health thread must free its slot."""
        factory = Mock(side_effect=make_channel)
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=0,
            max_size=1,
            max_idle_seconds=60.0,
            health_check_interval_seconds=0.05,
            channel_factory=factory,
        )

        with patch.object(pool, "_is_healthy", return_value=False):
            with pool.get_channel() as first:
                pass

            for _ in range(50):
                if pool.metrics()["evicted_total"] > 0:
                    break
                time.sleep(0.01)

            # A new acquire should succeed because the evicted channel's permit was
            # released back to the pool.
            acquired = threading.Event()
            result = []

            def try_acquire():
                try:
                    with pool.get_channel() as ch:
                        result.append(("ok", ch))
                except Exception as exc:
                    result.append(("err", exc))
                acquired.set()

            thread = threading.Thread(target=try_acquire)
            thread.start()
            acquired.wait(timeout=1)
            thread.join(timeout=1)

        pool.close_all()
        assert result and result[0][0] == "ok"
        assert factory.call_count == 2
        assert result[0][1] is not first

    def test_close_all_unblocks_waiting_acquire(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1, channel_factory=factory)

        acquired_event = threading.Event()
        released_event = threading.Event()
        acquire_error: Exception | None = None

        def holder() -> None:
            with pool.get_channel():
                acquired_event.set()
                released_event.wait()

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        acquired_event.wait(timeout=1)

        waiter_started = threading.Event()

        def waiter() -> None:
            nonlocal acquire_error
            waiter_started.set()
            try:
                with pool.get_channel():
                    pass  # Should not reach here.
            except Exception as exc:
                acquire_error = exc

        waiter_thread = threading.Thread(target=waiter)
        waiter_thread.start()
        waiter_started.wait(timeout=1)
        time.sleep(0.05)

        pool.close_all()
        released_event.set()
        holder_thread.join(timeout=1)
        waiter_thread.join(timeout=1)

        assert isinstance(acquire_error, RuntimeError)
        assert "closed" in str(acquire_error).lower()

    def test_release_after_close_all_restores_semaphore(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=1, channel_factory=factory)

        channel = pool.acquire()
        pool.close_all()

        # The channel is no longer tracked but the in-flight borrower can still
        # release its permit without leaking semaphore capacity.
        pool.release(channel)
        assert pool.metrics()["pool_size"] == 0
        # A new acquire must still report the pool is closed.
        with pytest.raises(RuntimeError, match="closed"):
            pool.acquire()


class TestGrpcChannelPoolMetrics:
    def test_metrics_reflect_state(self):
        pool = GrpcChannelPool("svc:50051", min_size=0, max_size=2, channel_factory=channel_factory)
        ch1 = pool.acquire()
        ch2 = pool.acquire()
        metrics = pool.metrics()
        assert metrics == {"pool_size": 2, "idle": 0, "in_use": 2, "evicted_total": 0}
        pool.release(ch1)
        pool.release(ch2)
        metrics = pool.metrics()
        assert metrics == {"pool_size": 2, "idle": 2, "in_use": 0, "evicted_total": 0}
        pool.close_all()


class TestGrpcChannelPoolContextManager:
    def test_context_manager_closes_all(self):
        factory = Mock(return_value=make_channel())
        with (
            GrpcChannelPool("svc:50051", min_size=0, max_size=1, channel_factory=factory) as pool,
            pool.get_channel() as channel,
        ):
            assert channel is factory.return_value

        factory.return_value.close.assert_called_once()


class TestGrpcChannelPoolWarmMin:
    def test_warms_up_to_min_size(self):
        factory = Mock(return_value=make_channel())
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=3,
            max_size=5,
            health_check_interval_seconds=0.05,
            channel_factory=factory,
        )
        # Trigger health thread which warms channels in the background.
        pool._start_health_thread()
        for _ in range(50):
            if pool.metrics()["idle"] >= 3:
                break
            time.sleep(0.01)

        pool.close_all()
        assert factory.call_count >= 3

    def test_warm_failure_is_logged(self):
        factory = Mock(side_effect=RuntimeError("cannot connect"))
        pool = GrpcChannelPool(
            "svc:50051",
            min_size=1,
            max_size=2,
            channel_factory=factory,
        )
        pool._warm_min_channels()
        assert factory.call_count == 1
        assert pool.metrics()["pool_size"] == 0


class TestPooledChannel:
    def test_defaults(self):
        channel = make_channel()
        wrapper = _PooledChannel(channel=channel)
        assert wrapper.channel is channel
        assert wrapper.in_use is False
        assert wrapper.last_used > 0
