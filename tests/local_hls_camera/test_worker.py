"""Exercise the real demux/remux thread, recovery and HA lifecycle contract."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import av
import pytest

from custom_components.local_hls_camera.stream import StreamAdapter


@pytest.mark.asyncio
async def test_worker_publishes_and_stops_without_pending_data(hass, synthetic_video):
    adapter = StreamAdapter(
        hass, "thread", "camera.source", 1, 3, SimpleNamespace(preload_stream=False)
    )
    original_open = av.open

    def open_fixture(*args, **kwargs):
        if args and args[0] == "rtsp://127.0.0.1/synthetic":
            return original_open(str(synthetic_video))
        return original_open(*args, **kwargs)

    with (
        patch(
            "custom_components.local_hls_camera.stream.async_get_stream_source",
            return_value="rtsp://127.0.0.1/synthetic",
        ),
        patch(
            "custom_components.local_hls_camera.stream.av.open",
            side_effect=open_fixture,
        ),
    ):
        await adapter.start()
        thread = adapter._thread
        await adapter.wait_ready()
        assert adapter.ring.ready
        assert adapter.ring.info.width == 320
        assert thread.is_alive()
        adapter.endpoint_url("hls")
        await adapter.stop()
        assert not thread.is_alive()
        assert adapter._thread is None
        assert adapter._idle_task is None
        assert not adapter.sessions
        assert adapter.ring.bytes == 0


@pytest.mark.asyncio
async def test_worker_failure_reconnects_with_safe_error_codes(hass, synthetic_video):
    adapter = StreamAdapter(
        hass, "recover", "camera.source", 1, 3, SimpleNamespace(preload_stream=False)
    )
    original_open = av.open
    calls = 0

    def temporarily_offline(*args, **kwargs):
        nonlocal calls
        if args and args[0] == "rtsp://127.0.0.1/synthetic":
            calls += 1
            if calls == 1:
                raise RuntimeError("rtsp://user:never-log-this@camera/")
            return original_open(str(synthetic_video))
        return original_open(*args, **kwargs)

    with (
        patch(
            "custom_components.local_hls_camera.stream.async_get_stream_source",
            return_value="rtsp://127.0.0.1/synthetic",
        ),
        patch(
            "custom_components.local_hls_camera.stream.av.open",
            side_effect=temporarily_offline,
        ),
    ):
        await adapter.start()
        await asyncio.sleep(0.05)
        assert adapter.last_error == "media_io_error"
        assert "never-log-this" not in repr(adapter.get_diagnostics())
        await adapter.wait_ready()
        assert calls >= 2
        assert adapter.ring.ready
        assert adapter.ring.segments[0].discontinuity
        await adapter.stop()


@pytest.mark.asyncio
async def test_idle_stops_unless_native_preload_is_enabled(hass, synthetic_video):
    adapter = StreamAdapter(
        hass, "idle", "camera.source", 1, 3, SimpleNamespace(preload_stream=False)
    )

    # A stoppable worker replaces only the media source, not HA's idle logic.
    def worker(source):
        adapter._quit.wait()

    with (
        patch.object(adapter, "_run", side_effect=worker),
        patch(
            "custom_components.local_hls_camera.stream.async_get_stream_source",
            return_value="rtsp://127.0.0.1/synthetic",
        ),
        patch("custom_components.local_hls_camera.stream.IDLE_SECONDS", 0),
    ):
        await adapter.start()
        adapter._last_request = time.monotonic() - 10
        await asyncio.sleep(5.1)
        assert adapter._thread is None
    assert not [t for t in threading.enumerate() if t.name == "local_hls_camera_idle"]
