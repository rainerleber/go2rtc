"""Synthetic RTSP → real worker → independently decoded MPEG-TS, end to end."""

import asyncio
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import av
import pytest

from custom_components.local_hls_camera.stream import StreamAdapter


@pytest.mark.asyncio
async def test_real_loopback_rtsp_source(hass, synthetic_video):
    binary = os.environ.get("GO2RTC_TEST_BINARY") or shutil.which("go2rtc")
    if not binary:
        pytest.skip(
            "Set GO2RTC_TEST_BINARY to enable the synthetic RTSP integration test"
        )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = (
        f"exec:ffmpeg -hide_banner -loglevel error -re -stream_loop -1 "
        f"-i {shlex.quote(str(synthetic_video))} -map 0:v:0 -map 0:a:0 "
        "-c copy -f rtsp {output}"
    )
    config = {
        "api": {"listen": ""},
        "rtsp": {"listen": f"127.0.0.1:{port}"},
        "streams": {"synthetic": command},
    }
    process = subprocess.Popen(
        [binary, "-c", json.dumps(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    adapter = StreamAdapter(
        hass, "rtsp", "camera.source", 1, 3, SimpleNamespace(preload_stream=False)
    )
    try:
        for _ in range(60):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                assert process.poll() is None
                await asyncio.sleep(0.05)
        else:
            pytest.fail("Synthetic RTSP server did not start")
        with patch(
            "custom_components.local_hls_camera.stream.async_get_stream_source",
            return_value=f"rtsp://127.0.0.1:{port}/synthetic",
        ):
            await adapter.start()
            await adapter.wait_ready()
            first_sequence = adapter.ring.segments[-1].sequence
            for _ in range(80):
                if adapter.ring.segments[-1].sequence > first_sequence:
                    break
                await asyncio.sleep(0.05)
            assert adapter.ring.segments[-1].sequence > first_sequence
            segment = adapter.ring.segments[-1]
            with av.open(BytesIO(segment.data), format="mpegts") as decoded:
                assert decoded.streams.audio[0].codec_context.name == "aac"
                frames = list(decoded.decode(video=0))
                assert frames[0].key_frame
                assert len(frames) >= 14
                assert frames[0].width == 320
    finally:
        await adapter.stop()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            await hass.async_add_executor_job(process.wait, 5)
