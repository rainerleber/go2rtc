"""Fixtures contain synthetic media only, never a user's camera data."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiohttp import ClientSession, web
from homeassistant.auth import auth_manager_from_config
from homeassistant.components.http.auth import async_setup_auth
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
)
from homeassistant.helpers.http import KEY_HASS

from custom_components.local_hls_camera.backend import BackendClient


@pytest_asyncio.fixture
async def backend_session(monkeypatch):
    """Use real HTTP without initializing HA's unrelated mDNS/network stack."""
    async with ClientSession() as session:
        monkeypatch.setattr(
            "custom_components.local_hls_camera.backend.async_get_clientsession",
            lambda hass: session,
        )
        yield session


@pytest.fixture
def backend(hass):
    value = BackendClient(hass, "synthetic")
    value.test_status = {
        "api_version": 1,
        "generation": "a" * 32,
        "ready": True,
        "running": True,
        "segment_seconds": 1,
        "segment_count": 6,
        "buffer_segments": 6,
        "buffer_bytes": 1000,
    }
    value.status = AsyncMock(side_effect=lambda: dict(value.test_status))
    value.start = AsyncMock()

    async def media(filename, **kwargs):
        return {
            "master.m3u8": (
                b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n"
                b'#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS="avc1.4d401f,mp4a.40.2",'
                b"RESOLUTION=320x180\nstream.m3u8\n"
            ),
            "stream.m3u8": (
                b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n"
                b"#EXT-X-MEDIA-SEQUENCE:1\n#EXT-X-INDEPENDENT-SEGMENTS\n"
                b"#EXTINF:1.000000,\nsegment-1.ts\n"
            ),
            "segment-1.ts": b"synthetic-transport-data",
            "snapshot.jpg": b"synthetic-snapshot",
        }[filename]

    value.request = AsyncMock(side_effect=media)
    return value


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-media") / "camera.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=15",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-profile:v",
            "main",
            "-level:v",
            "3.1",
            "-g",
            "15",
            "-keyint_min",
            "15",
            "-sc_threshold",
            "0",
            "-bf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest_asyncio.fixture
async def hass(tmp_path):
    source = Path(__file__).parents[2] / "custom_components" / "local_hls_camera"
    shutil.copytree(source, tmp_path / "custom_components" / "local_hls_camera")
    instance = HomeAssistant(str(tmp_path))
    instance.config.time_zone = "UTC"
    instance.config.skip_pip = True
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    await floor_registry.async_load(instance)
    await area_registry.async_load(instance)
    device_registry.async_setup(instance)
    await device_registry.async_load(instance)
    await entity_registry.async_load(instance)
    instance.auth = await auth_manager_from_config(instance, [], [])
    app = web.Application()
    app[KEY_HASS] = instance
    await async_setup_auth(instance, app)
    instance.data["extension_test_app"] = app
    yield instance
    await instance.async_stop()
