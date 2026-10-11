"""Synthetic RTSP → app HLS → real HA signatures → independent TS decoder."""

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

from custom_components.local_hls_camera.const import DOMAIN
from custom_components.local_hls_camera.http import HlsView
from custom_components.local_hls_camera.stream import StreamAdapter


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
async def test_real_app_backend_and_authenticated_ha_path(
    hass, synthetic_video, aiohttp_client, backend_session
):
    binary = os.environ.get("GO2RTC_TEST_BINARY") or shutil.which("go2rtc")
    if not binary:
        pytest.skip("Set GO2RTC_TEST_BINARY to test the real app HLS backend")
    rtsp_port, api_port = free_port(), free_port()
    command = (
        f"exec:ffmpeg -hide_banner -loglevel error -re -stream_loop -1 "
        f"-i {shlex.quote(str(synthetic_video))} -map 0:v:0 -map 0:a:0 "
        "-c copy -f rtsp {output}"
    )
    config = {
        "api": {"listen": f"127.0.0.1:{api_port}"},
        "rtsp": {"listen": f"127.0.0.1:{rtsp_port}"},
        "streams": {"synthetic": command},
        "hls": {
            "stream": "synthetic",
            "segment_seconds": 1,
            "segment_count": 6,
            "preload": True,
        },
    }

    def launch():
        return subprocess.Popen(
            [binary, "-c", json.dumps(config)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    async def stop(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            await hass.async_add_executor_job(process.wait, 5)

    process = launch()
    adapter = StreamAdapter(
        hass, "rtsp", "synthetic", SimpleNamespace(preload_stream=False)
    )
    adapter.entity_id = "camera.test"
    hass.data[DOMAIN] = {"rtsp": adapter}
    app = hass.data["extension_test_app"]
    HlsView(hass).register(hass, app, app.router)
    client = await aiohttp_client(app)
    try:
        with patch(
            "custom_components.local_hls_camera.backend.API_BASE",
            f"http://127.0.0.1:{api_port}/api/hls/v1",
        ):
            for _ in range(80):
                try:
                    reader, writer = await asyncio.open_connection(
                        "127.0.0.1", api_port
                    )
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    assert process.poll() is None
                    await asyncio.sleep(0.05)
            await adapter.start()
            await adapter.wait_ready()
            master_url = adapter.endpoint_url("hls")
            master = await client.get(master_url)
            assert master.status == 200
            child_url = (await master.text()).splitlines()[-1]
            assert "authSig=" in child_url
            child = await client.get(child_url)
            first = (await child.text()).splitlines()
            first_sequence = int(
                next(line.split(":")[1] for line in first if "MEDIA-SEQUENCE" in line)
            )
            media_uris = {}
            # Cross fixture loops and >=12 live-window rotations, not just startup.
            for _ in range(80):
                child = await client.get(child_url)
                assert child.status == 200
                lines = (await child.text()).splitlines()
                sequence = int(
                    next(
                        line.split(":")[1] for line in lines if "MEDIA-SEQUENCE" in line
                    )
                )
                assert adapter.last_error is None
                assert "EXT-X-MAP" not in "\n".join(lines)
                assert not any("127.0.0.1" in line for line in lines)
                children = [line for line in lines if not line.startswith("#")]
                for index, uri in enumerate(children):
                    number = sequence + index
                    assert media_uris.setdefault(number, uri) == uri
                master_again = await client.get(master_url)
                assert (await master_again.text()).splitlines()[-1] == child_url
                if sequence >= first_sequence + 12:
                    break
                await asyncio.sleep(0.25)
            assert sequence >= first_sequence + 12
            segment = await client.get(lines[-1])
            data = await segment.read()
            assert segment.status == 200
            assert (await client.get(lines[-1].split("?")[0])).status == 401
            with av.open(BytesIO(data), format="mpegts") as decoded:
                assert decoded.streams.audio[0].codec_context.name == "aac"
                frames = list(decoded.decode(video=0))
                assert frames[0].key_frame
                assert len(frames) >= 14
                assert frames[0].width == 320
            snapshot = await adapter.async_get_image()
            assert snapshot.startswith(b"\xff\xd8")
            assert adapter.get_diagnostics()["media_owner"] == "app"
            generation = adapter._status["generation"]
            await stop(process)
            process = launch()
            for _ in range(100):
                try:
                    status = await adapter.refresh()
                    if status["ready"] and status["generation"] != generation:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            assert status["ready"] and status["generation"] != generation
            assert (await client.get(master_url)).status == 410
            assert (await client.get(adapter.endpoint_url("hls"))).status == 200
    finally:
        await adapter.stop()
        await stop(process)
