"""The bridge cannot be used as an open HTTP proxy or unbounded media reader."""

from unittest.mock import patch

import pytest
from aiohttp import web

from custom_components.local_hls_camera.backend import (
    BackendClient,
    BackendError,
    rewrite_playlist,
)
from custom_components.local_hls_camera.const import MAX_SEGMENT_BYTES


@pytest.mark.parametrize(
    "name",
    ["../file", "http://camera/video", "user@camera", "a?token=secret", "", "x" * 65],
)
def test_only_stream_names_are_configurable(hass, name):
    with pytest.raises(BackendError, match="invalid_stream"):
        BackendClient(hass, name)


@pytest.mark.asyncio
async def test_no_arbitrary_fetch_target(hass, backend_session):
    client = BackendClient(hass, "synthetic")
    for filename in [
        "../file",
        "http://camera/video",
        "segment-1.ts?target=secret",
        "segment--1.ts",
    ]:
        with pytest.raises(BackendError, match="invalid_media_path"):
            await client.request(filename)
    with pytest.raises(BackendError, match="invalid_generation"):
        await client.request("segment-1.ts", generation="../secret")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["redirect", "large", "generation", "status"])
async def test_invalid_app_responses_are_bounded(
    hass, aiohttp_server, backend_session, mode
):
    async def respond(request):
        if mode == "redirect":
            raise web.HTTPFound("http://192.0.2.1/never-fetch")
        if mode == "large":
            return web.Response(body=b"x" * (MAX_SEGMENT_BYTES + 1))
        if mode == "generation":
            return web.Response(
                body=b"synthetic", headers={"X-HLS-Generation": "b" * 32}
            )
        return web.json_response({"api_version": 2, "ready": True})

    app = web.Application()
    app.router.add_get("/synthetic/{filename}", respond)
    server = await aiohttp_server(app)
    client = BackendClient(hass, "synthetic")
    with patch(
        "custom_components.local_hls_camera.backend.API_BASE",
        str(server.make_url("")).rstrip("/"),
    ):
        with pytest.raises(BackendError):
            if mode == "status":
                await client.status()
            else:
                await client.request(
                    "segment-1.ts",
                    generation="a" * 32 if mode == "generation" else None,
                )


@pytest.mark.parametrize(
    "child",
    [
        "http://camera/stream.m3u8",
        "../stream.m3u8",
        "/api/other",
        '#EXT-X-MAP:URI="secret"',
        '#EXT-X-KEY:URI="secret"',
    ],
)
def test_playlist_may_only_reference_signed_local_children(child):
    body = f"#EXTM3U\n#EXT-X-VERSION:3\n{child}\n".encode()
    with pytest.raises(BackendError, match="invalid_playlist"):
        rewrite_playlist(body, "master.m3u8", lambda name: name)
