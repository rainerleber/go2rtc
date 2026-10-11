"""HA camera contract and signed sessions only; all media lives in the app."""

import asyncio
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .backend import BackendClient, BackendError, GenerationExpired, rewrite_playlist
from .const import DOMAIN, MAX_SESSIONS, SESSION_SECONDS, STARTUP_SECONDS


@dataclass
class PlaybackSession:
    expires: float
    generation: str | None = None


class StreamAdapter:
    """A narrow internal HA adapter; no PyAV, worker thread or segment buffer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        stream_name: str,
        dynamic_stream_settings: Any,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.dynamic_stream_settings = dynamic_stream_settings
        self.backend = BackendClient(hass, stream_name)
        self.sessions: OrderedDict[str, PlaybackSession] = OrderedDict()
        self.entity_id: str | None = None
        self._available = True
        self._update_callback = None
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._status: dict = {}
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return self._available

    def set_update_callback(self, callback) -> None:
        self._update_callback = callback

    def _update(self, available: bool) -> None:
        if self._available != available:
            self._available = available
            if self._update_callback is not None:
                self._update_callback()

    def add_provider(self, fmt: str, timeout: int | None = None) -> StreamAdapter:
        if fmt != "hls":
            raise HomeAssistantError("Local HLS Camera only supports HLS playback")
        return self

    async def refresh(self) -> dict:
        try:
            self._status = await self.backend.status()
            self.last_error = (
                None
                if self._status["ready"]
                else self._status.get("last_error") or "stream_not_ready"
            )
            # An idle app is reachable and can be started by native HA/Alexa.
            # Marking an idle camera unavailable would prevent that cold start.
            self._update(self._status["ready"] or not self._status["running"])
            return self._status
        except BackendError as error:
            self.last_error = str(error)
            self._status = {}
            self._update(False)
            raise

    async def start(self) -> None:
        async with self._lock:
            self.start_monitor()
            try:
                await self.backend.start()
                await self.refresh()
            except BackendError:
                raise HomeAssistantError(
                    "Local HLS Camera app is unavailable"
                ) from None

    def start_monitor(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = self.hass.async_create_background_task(
                self._monitor(), f"{DOMAIN} app monitor"
            )

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                if self.dynamic_stream_settings.preload_stream:
                    await self.backend.start()
                await self.refresh()
            except BackendError:
                pass

    def endpoint_url(self, fmt: str) -> str:
        self.add_provider(fmt)
        now = time.monotonic()
        for session, value in list(self.sessions.items()):
            if value.expires <= now:
                del self.sessions[session]
        while len(self.sessions) >= MAX_SESSIONS:
            self.sessions.popitem(last=False)
        session = secrets.token_hex(16)
        self.sessions[session] = PlaybackSession(
            now + SESSION_SECONDS,
            self._status.get("generation") if self._status.get("ready") else None,
        )
        return self.signed_url(session, "master.m3u8")

    def valid_session(self, session: str) -> bool:
        if self.sessions.get(session, PlaybackSession(0)).expires <= time.monotonic():
            self.sessions.pop(session, None)
            return False
        return True

    def signed_url(self, session: str, filename: str) -> str:
        if not self.valid_session(session):
            raise HomeAssistantError("Local HLS Camera session expired")
        remaining = max(1, int(self.sessions[session].expires - time.monotonic()))
        return async_sign_path(
            self.hass,
            f"/api/{DOMAIN}/{self.entry_id}/{session}/{filename}",
            timedelta(seconds=remaining),
            use_content_user=True,
        )

    async def wait_ready(self) -> dict:
        async with asyncio.timeout(STARTUP_SECONDS):
            while True:
                status = await self.refresh()
                if status["ready"] and status["generation"]:
                    return status
                await asyncio.sleep(0.1)

    async def media(self, session: str, filename: str) -> bytes | str:
        value = self.sessions.get(session)
        if value is None or not self.valid_session(session):
            raise GenerationExpired("session_expired")
        status = await self.wait_ready()
        if not self.valid_session(session):
            raise GenerationExpired("session_expired")
        if value.generation is None:
            value.generation = status["generation"]
        elif value.generation != status["generation"]:
            self.sessions.pop(session, None)
            raise GenerationExpired("generation_expired")
        body = await self.backend.request(filename, generation=value.generation)
        if filename.endswith(".m3u8"):
            return rewrite_playlist(
                body, filename, lambda name: self.signed_url(session, name)
            )
        return body

    async def async_get_image(
        self,
        width: int | None = None,
        height: int | None = None,
        wait_for_next_keyframe: bool = False,
    ) -> bytes | None:
        try:
            await self.backend.start()
            await self.wait_ready()
            return await self.backend.request("snapshot.jpg")
        except BackendError, TimeoutError:
            return None

    async def async_record(self, *args, **kwargs) -> None:
        raise HomeAssistantError("Local HLS Camera does not make recordings")

    def get_diagnostics(self) -> dict:
        return {
            "running": self._status.get("running", False),
            "ready": self._status.get("ready", False),
            "buffer_segments": self._status.get("buffer_segments", 0),
            "buffer_bytes": self._status.get("buffer_bytes", 0),
            "media_owner": "app",
            "last_error": self.last_error,
        }

    async def stop(self) -> None:
        async with self._lock:
            self.sessions.clear()
            self._status = {}
            task, self._monitor_task = self._monitor_task, None
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            # Do not stop a shared/preloaded app backend when one HA entity unloads.
            self._update(True)
