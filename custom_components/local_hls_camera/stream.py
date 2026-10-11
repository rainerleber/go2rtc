"""Per-camera adapter for HA's internal stream contract, without monkeypatches."""

import asyncio
import logging
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import timedelta
from typing import Any

import av
from homeassistant.components.camera import async_get_image, async_get_stream_source
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .config_flow import source_is_rtsp
from .const import (
    DOMAIN,
    IDLE_SECONDS,
    IO_TIMEOUT_SECONDS,
    MAX_SESSIONS,
    SESSION_SECONDS,
    STARTUP_SECONDS,
)
from .media import MediaError, MediaInfo, Remuxer, SegmentRing

_LOGGER = logging.getLogger(__name__)


class StreamAdapter:
    """The deliberately narrow, tested HA stream adapter for a single entity.

    HA's camera helper currently calls add_provider/start/endpoint_url. Camera
    availability, preload, snapshots and removal are also handled explicitly.
    This is an internal contract, not a stable public HLS-provider API.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        source_entity_id: str,
        segment_seconds: float,
        segment_count: int,
        dynamic_stream_settings: Any,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.source_entity_id = source_entity_id
        self.dynamic_stream_settings = dynamic_stream_settings
        self.ring = SegmentRing(segment_count, segment_seconds)
        self.segment_seconds = segment_seconds
        self.sessions: OrderedDict[str, float] = OrderedDict()
        self.entity_id: str | None = None
        self._available = True
        self._update_callback = None
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._thread: threading.Thread | None = None
        self._quit = threading.Event()
        self._idle_task: asyncio.Task | None = None
        self._last_request = time.monotonic()
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

    def touch(self) -> None:
        """Mark a permitted playback request as active."""
        self._last_request = time.monotonic()

    async def start(self) -> None:
        self.touch()
        async with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._quit.is_set():
                    raise HomeAssistantError("Local HLS Camera is stopping")
                return
            try:
                async with asyncio.timeout(IO_TIMEOUT_SECONDS):
                    source = await async_get_stream_source(
                        self.hass, self.source_entity_id
                    )
                if not source_is_rtsp(source):
                    raise MediaError("rtsp_source_required")
            except (HomeAssistantError, TimeoutError, MediaError) as error:
                self.last_error = (
                    str(error)
                    if isinstance(error, MediaError)
                    else "source_unavailable"
                )
                self._update(False)
                raise HomeAssistantError(
                    "Local HLS Camera source is unavailable"
                ) from None
            self._quit.clear()
            self._ready.clear()
            self.ring.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(source,),
                name=f"{DOMAIN}_{self.entry_id}",
                daemon=True,
            )
            self._thread.start()
            self._idle_task = self.hass.async_create_background_task(
                self._watch_idle(), f"{DOMAIN} idle watchdog"
            )

    async def _watch_idle(self) -> None:
        while True:
            await asyncio.sleep(5)
            if (
                not self.dynamic_stream_settings.preload_stream
                and time.monotonic() - self._last_request > IDLE_SECONDS
            ):
                await self.stop()
                return

    async def _publish(
        self, data: bytes, duration: float, discontinuity: bool, info: MediaInfo
    ) -> None:
        if self._quit.is_set():
            return
        self.ring.append(data, duration, discontinuity, info)
        self.last_error = None
        self._update(True)
        self._ready.set()

    def _publish_from_thread(
        self, data: bytes, duration: float, discontinuity: bool, info: MediaInfo
    ) -> None:
        # Wait for the loop to accept each segment. This bounds pending callback
        # memory as well as the ring itself when HA's event loop is overloaded.
        future = asyncio.run_coroutine_threadsafe(
            self._publish(data, duration, discontinuity, info), self.hass.loop
        )
        try:
            future.result(timeout=IO_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            future.cancel()
            raise MediaError("consumer_backpressure") from None

    async def _failed(self, code: str) -> None:
        if self._quit.is_set():
            return
        if self.last_error != code:
            _LOGGER.warning("Local HLS stream unavailable (%s)", code)
        self.last_error = code
        self.ring.clear()
        self._ready.clear()
        self._update(False)

    def _run(self, source: str) -> None:
        backoff = 1
        while not self._quit.is_set():
            container = None
            remuxer = None
            started = time.monotonic()
            code = "source_disconnected"
            try:
                with av.logging.Capture():
                    container = av.open(
                        source,
                        mode="r",
                        options={"rtsp_transport": "tcp"},
                        timeout=(IO_TIMEOUT_SECONDS, IO_TIMEOUT_SECONDS),
                    )
                remuxer = Remuxer(
                    container, self.segment_seconds, self._publish_from_thread
                )
                for packet in container.demux(remuxer.video, remuxer.audio):
                    if self._quit.is_set():
                        break
                    remuxer.feed(packet)
            except MediaError as error:
                code = str(error)
            except Exception:
                # PyAV/FFmpeg errors may contain credentials. Do not log their
                # text or traceback and do not put the source URL in diagnostics.
                code = "media_io_error"
            finally:
                if remuxer is not None:
                    try:
                        remuxer.close()
                    except Exception:
                        pass
                if container is not None:
                    try:
                        container.close()
                    except Exception:
                        pass
            if self._quit.is_set():
                return
            future = asyncio.run_coroutine_threadsafe(
                self._failed(code), self.hass.loop
            )
            try:
                future.result(timeout=IO_TIMEOUT_SECONDS)
            except FutureTimeoutError:
                future.cancel()
            if time.monotonic() - started > 60:
                backoff = 1
            if self._quit.wait(backoff):
                return
            backoff = min(backoff * 2, 15)

    def endpoint_url(self, fmt: str) -> str:
        self.add_provider(fmt)
        self.touch()
        now = time.monotonic()
        for session, expiration in list(self.sessions.items()):
            if expiration <= now:
                del self.sessions[session]
        while len(self.sessions) >= MAX_SESSIONS:
            self.sessions.popitem(last=False)
        session = secrets.token_hex(16)
        self.sessions[session] = now + SESSION_SECONDS
        return self.signed_url(session, "master.m3u8")

    def valid_session(self, session: str) -> bool:
        if self.sessions.get(session, 0) <= time.monotonic():
            self.sessions.pop(session, None)
            return False
        return True

    def signed_url(self, session: str, filename: str) -> str:
        if not self.valid_session(session):
            raise HomeAssistantError("Local HLS Camera session expired")
        remaining = max(1, int(self.sessions[session] - time.monotonic()))
        return async_sign_path(
            self.hass,
            f"/api/{DOMAIN}/{self.entry_id}/{session}/{filename}",
            timedelta(seconds=remaining),
            use_content_user=True,
        )

    async def wait_ready(self) -> None:
        self.touch()
        if self.ring.ready:
            return
        self._ready.clear()
        await asyncio.wait_for(self._ready.wait(), timeout=STARTUP_SECONDS)
        if not self.ring.ready:
            raise MediaError("stream_not_ready")

    async def async_get_image(
        self,
        width: int | None = None,
        height: int | None = None,
        wait_for_next_keyframe: bool = False,
    ) -> bytes | None:
        image = await async_get_image(
            self.hass, self.source_entity_id, width=width, height=height
        )
        return image.content

    async def async_record(self, *args, **kwargs) -> None:
        raise HomeAssistantError("Local HLS Camera does not make recordings")

    def get_diagnostics(self) -> dict:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "ready": self.ring.ready,
            "buffer_segments": len(self.ring.segments),
            "buffer_bytes": self.ring.bytes,
            "last_error": self.last_error,
        }

    async def stop(self) -> None:
        async with self._lock:
            self._quit.set()
            self.sessions.clear()
            self.ring.clear()
            self._ready.clear()
            task = self._idle_task
            self._idle_task = None
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if self._thread is not None:
                await self.hass.async_add_executor_job(self._thread.join, 12)
                if self._thread.is_alive():
                    _LOGGER.error(
                        "Local HLS worker did not stop within its I/O deadline"
                    )
                else:
                    self._thread = None
            self._update(True)
