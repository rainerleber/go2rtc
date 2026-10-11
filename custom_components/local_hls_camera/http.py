"""HA-owned authenticated media routes; no additional HTTP listener or proxy."""

import re

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_HASS_USER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .media import MediaError


class HlsView(HomeAssistantView):
    """HA validates its path-specific expiring signatures before this handler."""

    url = f"/api/{DOMAIN}/{{entry_id}}/{{session_id}}/{{filename}}"
    name = f"api:{DOMAIN}:media"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def head(
        self, request: web.Request, entry_id: str, session_id: str, filename: str
    ) -> web.Response:
        """Allow authenticated media probes; aiohttp suppresses the HEAD body."""
        return await self.get(request, entry_id, session_id, filename)

    async def get(
        self, request: web.Request, entry_id: str, session_id: str, filename: str
    ) -> web.Response:
        adapter = self.hass.data[DOMAIN].get(entry_id)
        if adapter is None or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise web.HTTPNotFound
        user = request[KEY_HASS_USER]
        if adapter.entity_id is None or not user.permissions.check_entity(
            adapter.entity_id, POLICY_READ
        ):
            raise web.HTTPForbidden
        if not adapter.valid_session(session_id):
            raise web.HTTPGone
        adapter.touch()
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        try:
            if filename in ("master.m3u8", "stream.m3u8"):
                await adapter.wait_ready()
                if filename == "master.m3u8":
                    body = adapter.ring.master(
                        adapter.signed_url(session_id, "stream.m3u8")
                    )
                else:
                    body = adapter.ring.playlist(
                        lambda sequence: adapter.signed_url(
                            session_id, f"segment-{sequence}.ts"
                        )
                    )
                return web.Response(
                    text=body,
                    content_type="application/vnd.apple.mpegurl",
                    headers=headers,
                )
            match = re.fullmatch(r"segment-([0-9]{1,20})\.ts", filename)
            if match is None:
                raise web.HTTPNotFound
            segment = adapter.ring.get(int(match[1]))
            if segment is None:
                raise web.HTTPNotFound
            return web.Response(
                body=segment.data, content_type="video/mp2t", headers=headers
            )
        except TimeoutError, MediaError:
            raise web.HTTPServiceUnavailable(headers={"Retry-After": "1"}) from None
        except HomeAssistantError:
            raise web.HTTPGone from None
