"""Use HA's real authentication middleware; test every media URL independently."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from homeassistant.components.http.const import KEY_HASS_USER

from custom_components.local_hls_camera.const import (
    DOMAIN,
    MAX_SESSIONS,
    MAX_SIGNED_SEGMENT_URLS,
)
from custom_components.local_hls_camera.http import HlsView
from custom_components.local_hls_camera.stream import StreamAdapter


@pytest.fixture
def adapter(hass, backend):
    value = StreamAdapter(
        hass, "entry", "synthetic", SimpleNamespace(preload_stream=False)
    )
    value.entity_id = "camera.test"
    value.backend = backend
    hass.data[DOMAIN] = {"entry": value}
    return value


@pytest.fixture
async def client(hass, aiohttp_client):
    app = hass.data["extension_test_app"]
    view = HlsView(hass)
    view.register(hass, app, app.router)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_all_playlist_and_segment_urls_are_signed(client, adapter):
    master_url = adapter.endpoint_url("hls")
    response = await client.get(master_url, headers={"Accept-Encoding": "identity"})
    assert response.status == 200
    assert "Content-Encoding" not in response.headers
    assert response.headers["Cache-Control"] == "no-store"
    child_url = (await response.text()).splitlines()[-1]
    assert "authSig=" in child_url
    child = await client.get(child_url, headers={"Accept-Encoding": "gzip"})
    assert child.status == 200
    assert "Content-Encoding" not in child.headers
    segment_url = (await child.text()).splitlines()[-1]
    assert "authSig=" in segment_url
    segment = await client.get(segment_url)
    assert segment.status == 200
    assert segment.headers["Content-Type"] == "video/mp2t"
    assert await segment.read() == b"synthetic-transport-data"
    assert (await client.head(segment_url)).status == 200
    assert (await client.head(segment_url.split("?")[0])).status == 401
    assert (await client.get(master_url.split("?")[0])).status == 401
    assert (await client.get(child_url.split("?")[0])).status == 401
    assert (await client.get(segment_url.split("?")[0])).status == 401
    assert (await client.get(master_url + "tampered")).status == 401
    # A signature for the master is not a general-purpose HA access token.
    assert (
        await client.get(master_url.replace("master.m3u8", "stream.m3u8"))
    ).status == 401
    assert (await client.get(master_url + "&target=http://example.com")).status == 401


@pytest.mark.asyncio
async def test_playlist_reload_keeps_identical_media_uris(client, adapter):
    """RFC 8216 6.3.4: a repeated segment must keep its complete signed URI."""
    master_url = adapter.endpoint_url("hls")
    response = await client.get(master_url)
    child_url = (await response.text()).splitlines()[-1]
    first = await client.get(child_url)
    segment_url = (await first.text()).splitlines()[-1]
    # HA includes an issued-at timestamp in each new signature. Cross a real
    # signing second, rather than only comparing calls in the same second.
    await asyncio.sleep(1.1)
    second = await client.get(child_url)
    assert second.status == 200
    assert (await second.text()).splitlines()[-1] == segment_url
    master_again = await client.get(master_url)
    assert (await master_again.text()).splitlines()[-1] == child_url
    assert (await client.get(segment_url)).status == 200


@pytest.mark.asyncio
async def test_expired_session_and_removed_camera(client, adapter):
    url = adapter.endpoint_url("hls")
    session = next(iter(adapter.sessions))
    adapter.sessions[session].expires = time.monotonic() - 1
    assert (await client.get(url)).status == 410
    adapter.hass.data[DOMAIN].clear()
    assert (await client.get(url)).status == 404


@pytest.mark.asyncio
async def test_signature_expiration_is_enforced_by_ha(client, adapter):
    from datetime import timedelta

    from homeassistant.components.http.auth import async_sign_path

    master = adapter.endpoint_url("hls")
    expired = async_sign_path(
        adapter.hass, master.split("?")[0], timedelta(seconds=-1), use_content_user=True
    )
    assert (await client.get(expired)).status == 401


@pytest.mark.asyncio
async def test_entity_permission_is_checked(hass, adapter):
    request = {
        KEY_HASS_USER: SimpleNamespace(
            permissions=SimpleNamespace(check_entity=lambda *args: False)
        )
    }
    session = adapter.endpoint_url("hls").split("/")[-2]
    with pytest.raises(web.HTTPForbidden):
        await HlsView(hass).get(request, "entry", session, "master.m3u8")


@pytest.mark.asyncio
async def test_bounded_sessions_and_stop_revokes_urls(adapter):
    for _ in range(MAX_SESSIONS + 3):
        adapter.endpoint_url("hls")
    assert len(adapter.sessions) == MAX_SESSIONS
    with pytest.raises(Exception, match="only supports HLS"):
        adapter.add_provider("recorder")
    await adapter.stop()
    assert not adapter.sessions
    assert not adapter._status
    adapter.backend.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_url_cache_is_bounded_and_preserves_playlist_urls(adapter):
    master = adapter.endpoint_url("hls")
    session = next(iter(adapter.sessions))
    child = adapter.signed_url(session, "stream.m3u8")
    value = adapter.sessions[session]
    for index in range(MAX_SIGNED_SEGMENT_URLS + 20):
        adapter.signed_url(session, f"segment-{index}.ts")
    assert len(value.segment_urls) == MAX_SIGNED_SEGMENT_URLS
    assert len(value.playlist_urls) == 2
    assert "segment-0.ts" not in value.segment_urls
    assert adapter.signed_url(session, "master.m3u8") == master
    assert adapter.signed_url(session, "stream.m3u8") == child
    recent = adapter.signed_url(session, "segment-51.ts")
    adapter.signed_url(session, "segment-52.ts")
    assert adapter.signed_url(session, "segment-51.ts") == recent
    with pytest.raises(Exception, match="invalid media path"):
        adapter.signed_url(session, "../other")
    value.expires = time.monotonic() - 1
    with pytest.raises(Exception, match="session expired"):
        adapter.signed_url(session, "stream.m3u8")
    assert session not in adapter.sessions


@pytest.mark.asyncio
async def test_native_ha_camera_helper_uses_our_adapter(hass, adapter):
    from homeassistant.components.camera.helper import async_stream_endpoint_url

    camera = SimpleNamespace(async_create_stream=lambda: _return(adapter))
    with patch.object(adapter, "start", return_value=None) as start:
        url = await async_stream_endpoint_url(hass, camera, "hls")
    assert "/api/local_hls_camera/" in url
    start.assert_awaited_once()


async def _return(value):
    return value


@pytest.mark.asyncio
async def test_app_restart_revokes_old_session_urls(client, adapter):
    url = adapter.endpoint_url("hls")
    assert (await client.get(url)).status == 200
    adapter.backend.test_status["generation"] = "b" * 32
    assert (await client.get(url)).status == 410
    assert (await client.get(adapter.endpoint_url("hls"))).status == 200


@pytest.mark.asyncio
async def test_startup_timeout(adapter):
    adapter.backend.test_status["ready"] = False
    with patch("custom_components.local_hls_camera.stream.STARTUP_SECONDS", 0.01):
        with pytest.raises(asyncio.TimeoutError):
            await adapter.wait_ready()


@pytest.mark.asyncio
async def test_idle_camera_stays_available_for_native_cold_start(adapter):
    adapter.backend.test_status.update(ready=False, running=False)
    await adapter.refresh()
    assert adapter.available
    assert adapter.last_error == "stream_not_ready"


@pytest.mark.asyncio
async def test_snapshot_comes_from_app_without_generic_camera(adapter):
    assert await adapter.async_get_image(width=320, height=180) == b"synthetic-snapshot"
    adapter.backend.request.assert_awaited_once_with("snapshot.jpg")
