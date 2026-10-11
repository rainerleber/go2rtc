"""Safe automatic migration and app-only configuration, preserving camera IDs."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.local_hls_camera import async_migrate_entry
from custom_components.local_hls_camera.backend import BackendError
from custom_components.local_hls_camera.config_flow import (
    LocalHlsConfigFlow,
    legacy_stream_name,
)


def test_migration_extracts_only_local_app_output():
    assert (
        legacy_stream_name("rtsp://127.0.0.1:8554/camera_compatible")
        == "camera_compatible"
    )


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
        "rtsp://127.0.0.1:8554/output\n",
        "rtsp://user:secret@127.0.0.1:8554/output",
        "rtsp://@127.0.0.1:8554/output",
        "rtsp://camera:8554/output",
        "rtsp://127.0.0.1:8554/output?token=secret",
        "rtsp://127.0.0.1:8554/../output",
        "rtsp://127.0.0.1:554/output",
    ],
)
def test_unsafe_legacy_sources(source):
    assert legacy_stream_name(source) is None


@pytest.mark.asyncio
async def test_config_form_is_ui_native(hass):
    flow = LocalHlsConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert {str(key) for key in result["data_schema"].schema} == {"name", "stream_name"}


@pytest.mark.asyncio
async def test_invalid_app_is_rejected_safely(hass):
    flow = LocalHlsConfigFlow()
    flow.hass = hass
    with patch(
        "custom_components.local_hls_camera.config_flow.BackendClient.status",
        side_effect=BackendError("app_unavailable"),
    ):
        result = await flow.async_step_user(
            {"name": "Test", "stream_name": "synthetic"}
        )
    assert result["errors"] == {"stream_name": "app_unavailable"}


@pytest.mark.asyncio
async def test_migration_preserves_entry_and_entity_id(hass, backend):
    from homeassistant.config_entries import ConfigEntry

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain="local_hls_camera",
        title="Haustür",
        data={"source_entity_id": "camera.source"},
        options={"segment_seconds": 1, "segment_count": 6},
        source="user",
        unique_id="camera.source",
        discovery_keys={},
        subentries_data=[],
    )
    original_id = entry.entry_id
    with (
        patch(
            "custom_components.local_hls_camera.async_get_stream_source",
            return_value="rtsp://127.0.0.1:8554/synthetic",
        ),
        patch("custom_components.local_hls_camera.BackendClient", return_value=backend),
        patch.object(hass.config_entries, "async_update_entry") as update,
    ):
        assert await async_migrate_entry(hass, entry)
    assert entry.entry_id == original_id
    assert entry.title == "Haustür"
    update.assert_called_once_with(
        entry,
        data={"stream_name": "synthetic"},
        options={},
        version=2,
        unique_id="go2rtc:synthetic",
    )


@pytest.mark.asyncio
async def test_migration_does_not_silently_change_segment_settings(hass, backend):
    entry = SimpleNamespace(
        version=1,
        data={"source_entity_id": "camera.source"},
        options={"segment_count": 10},
    )
    with (
        patch(
            "custom_components.local_hls_camera.async_get_stream_source",
            return_value="rtsp://127.0.0.1:8554/synthetic",
        ),
        patch("custom_components.local_hls_camera.BackendClient", return_value=backend),
        patch.object(hass.config_entries, "async_update_entry") as update,
    ):
        assert not await async_migrate_entry(hass, entry)
    update.assert_not_called()


@pytest.mark.asyncio
async def test_unloaded_generic_source_can_migrate_without_waiting_for_camera(
    hass, backend
):
    source_entry = SimpleNamespace(
        options={"stream_source": "rtsp://127.0.0.1:8554/synthetic"}, data={}
    )
    registered = SimpleNamespace(platform="generic", config_entry_id="source")
    entry = SimpleNamespace(
        version=1, data={"source_entity_id": "camera.source"}, options={}
    )
    with (
        patch(
            "custom_components.local_hls_camera.er.async_get",
            return_value=SimpleNamespace(async_get=lambda entity_id: registered),
        ),
        patch.object(hass.config_entries, "async_get_entry", return_value=source_entry),
        patch.object(hass.config_entries, "async_update_entry") as update,
        patch(
            "custom_components.local_hls_camera.async_get_stream_source"
        ) as read_source,
        patch("custom_components.local_hls_camera.BackendClient", return_value=backend),
    ):
        assert await async_migrate_entry(hass, entry)
    update.assert_called_once()
    read_source.assert_not_called()


@pytest.mark.asyncio
async def test_no_media_worker_and_unload_does_not_stop_app(hass, backend):
    from custom_components.local_hls_camera.stream import StreamAdapter

    adapter = StreamAdapter(
        hass, "entry", "synthetic", SimpleNamespace(preload_stream=True)
    )
    adapter.backend = backend
    await adapter.start()
    assert adapter._monitor_task is not None
    assert not hasattr(adapter, "ring")
    assert not hasattr(adapter, "_thread")
    await adapter.stop()
    assert adapter._monitor_task is None
    assert not adapter.sessions
    backend.start.assert_awaited_once()
