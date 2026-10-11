"""Set up and unload the actual custom camera platform in isolated HA."""

import shutil
import socket
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.components.camera import DATA_COMPONENT, Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.local_hls_camera.const import DOMAIN


class SourceCamera(Camera):
    _attr_name = "Synthetic source"
    _attr_supported_features = CameraEntityFeature.STREAM

    async def stream_source(self):
        return "rtsp://127.0.0.1/synthetic"


@pytest.mark.asyncio
async def test_real_ha_config_flow_platform_and_unload(tmp_path):
    source = Path(__file__).parents[2] / "custom_components" / DOMAIN
    shutil.copytree(source, tmp_path / "custom_components" / DOMAIN)
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        configured = await async_from_config_dict(
            {
                "homeassistant": {"time_zone": "UTC"},
                "http": {"server_host": "127.0.0.1", "server_port": port},
                "camera": {},
                "stream": {},
            },
            hass,
        )
        assert configured is hass
        await hass.data[DATA_COMPONENT].async_add_entities([SourceCamera()])
        await hass.async_block_till_done()
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert flow["type"] == "form"
        status = {
            "api_version": 1,
            "ready": True,
            "generation": "a" * 32,
            "running": True,
            "segment_seconds": 1,
            "segment_count": 6,
            "buffer_segments": 6,
            "buffer_bytes": 1000,
        }
        with patch(
            "custom_components.local_hls_camera.backend.BackendClient.status",
            AsyncMock(return_value=status),
        ):
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {"name": "Compatibility Test", "stream_name": "synthetic"},
            )
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        entry = result["result"]
        assert entry.state.value == "loaded"
        entity = hass.data[DATA_COMPONENT].get_entity("camera.compatibility_test")
        assert entity is not None
        assert entity.stream is entity.adapter
        assert await entity.async_create_stream() is entity.adapter
        assert hass.states.get("camera.synthetic_source") is not None
        assert hass.states.get("camera.compatibility_test").state == "idle"
        # Exercise the actual native Alexa handler without sending any directive
        # to an Echo. The custom camera supplies the URL, not HA's fMP4 output.
        from types import SimpleNamespace

        from homeassistant.components.alexa.handlers import (
            async_api_initialize_camera_stream,
        )

        directive = SimpleNamespace(
            entity=SimpleNamespace(entity_id=entity.entity_id),
            response=lambda **kwargs: kwargs,
        )
        with (
            patch.object(entity.adapter, "start", return_value=None),
            patch(
                "homeassistant.components.alexa.handlers.network.get_url",
                return_value="https://camera.invalid",
            ),
        ):
            response = await async_api_initialize_camera_stream(
                hass, None, directive, None
            )
        assert response["payload"]["cameraStreams"][0]["uri"].startswith(
            "https://camera.invalid/api/local_hls_camera/"
        )
        assert response["payload"]["cameraStreams"][0]["protocol"] == "HLS"
        assert response["payload"]["cameraStreams"][0]["videoCodec"] == "H264"
        # Removing the integration stops only its own adapter.
        with patch.object(entity.adapter, "stop", return_value=None) as stop:
            assert await hass.config_entries.async_unload(entry.entry_id)
            stop.assert_awaited_once()
        assert entry.entry_id not in hass.data[DOMAIN]
        assert hass.states.get("camera.synthetic_source") is not None
    finally:
        await hass.async_stop()
