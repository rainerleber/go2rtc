"""Configuration must not accept arbitrary media protocols or recursive sources."""

from unittest.mock import patch

import pytest

from custom_components.local_hls_camera.config_flow import (
    LocalHlsConfigFlow,
    source_is_rtsp,
)


@pytest.mark.parametrize(
    "source", ["rtsp://127.0.0.1:8554/output", "rtsps://camera/stream"]
)
def test_rtsp_source(source):
    assert source_is_rtsp(source)


@pytest.mark.parametrize(
    "source",
    [
        None,
        "",
        "file:///etc/passwd",
        "exec:command",
        "http://camera/",
        "rtsp://",
        "rtsp://[bad",
        "rtsp://camera/\n",
    ],
)
def test_unsafe_sources(source):
    assert not source_is_rtsp(source)


@pytest.mark.asyncio
async def test_config_form_is_ui_native(hass):
    flow = LocalHlsConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert {str(key) for key in result["data_schema"].schema} == {
        "name",
        "source_entity_id",
    }


@pytest.mark.asyncio
async def test_invalid_source_is_rejected_without_returning_credentials(hass):
    flow = LocalHlsConfigFlow()
    flow.hass = hass
    with patch(
        "custom_components.local_hls_camera.config_flow.async_get_stream_source",
        return_value="http://user:secret@camera/video",
    ):
        result = await flow.async_step_user(
            {"name": "Test", "source_entity_id": "camera.source"}
        )
    assert result["errors"] == {"source_entity_id": "invalid_source"}
    assert "secret" not in repr(result)
