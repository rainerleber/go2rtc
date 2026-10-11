"""Fixtures contain synthetic media only, never a user's camera data."""

import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from homeassistant.auth import auth_manager_from_config
from homeassistant.components.http.auth import async_setup_auth
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
)
from homeassistant.helpers.http import KEY_HASS


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
