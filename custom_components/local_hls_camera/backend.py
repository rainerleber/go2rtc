"""Bounded HTTP client for the app's fixed loopback media contract."""

import json
import re

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import IO_TIMEOUT_SECONDS, MAX_IMAGE_BYTES, MAX_SEGMENT_BYTES

API_BASE = "http://127.0.0.1:1984/api/hls/v1"
STREAM_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
SEGMENT_NAME = re.compile(r"segment-[0-9]{1,20}\.ts")
GENERATION = re.compile(r"[a-f0-9]{32}")
MAX_METADATA_BYTES = 64 * 1024


class BackendError(Exception):
    """Only controlled error codes, never URLs or arbitrary response text."""


class GenerationExpired(BackendError):
    """An app restart revokes media URLs of the previous worker generation."""


class MediaNotFound(BackendError):
    """A requested segment is outside the retained live window."""


class BackendClient:
    """No host, credentials, executable URLs or proxy targets in HA config."""

    def __init__(self, hass: HomeAssistant, stream_name: str) -> None:
        if STREAM_NAME.fullmatch(stream_name) is None:
            raise BackendError("invalid_stream")
        self.hass = hass
        self.stream_name = stream_name

    async def request(
        self, filename: str, *, generation: str | None = None, method: str = "GET"
    ) -> bytes:
        if (
            filename
            not in ("start", "status", "master.m3u8", "stream.m3u8", "snapshot.jpg")
            and SEGMENT_NAME.fullmatch(filename) is None
        ):
            raise BackendError("invalid_media_path")
        if generation is not None and GENERATION.fullmatch(generation) is None:
            raise BackendError("invalid_generation")
        limit = MAX_METADATA_BYTES
        if filename.endswith(".ts"):
            limit = MAX_SEGMENT_BYTES
        elif filename == "snapshot.jpg":
            limit = MAX_IMAGE_BYTES
        try:
            async with async_get_clientsession(self.hass).request(
                method,
                f"{API_BASE}/{self.stream_name}/{filename}",
                params={"generation": generation} if generation else None,
                timeout=ClientTimeout(total=IO_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                if response.status == 410:
                    raise GenerationExpired("generation_expired")
                if response.status == 404:
                    raise MediaNotFound("media_not_found")
                if response.status != (204 if method == "POST" else 200):
                    raise BackendError("app_unavailable")
                if (
                    generation
                    and response.headers.get("X-HLS-Generation") != generation
                ):
                    raise GenerationExpired("generation_expired")
                if (
                    response.content_length is not None
                    and response.content_length > limit
                ):
                    raise BackendError("response_too_large")
                body = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > limit:
                        raise BackendError("response_too_large")
                return bytes(body)
        except ClientError, TimeoutError:
            raise BackendError("app_unavailable") from None

    async def start(self) -> None:
        await self.request("start", method="POST")

    async def status(self) -> dict:
        try:
            status = json.loads(await self.request("status"))
            if (
                not isinstance(status, dict)
                or status.get("api_version") != 1
                or type(status.get("ready")) is not bool
                or type(status.get("running")) is not bool
                or not isinstance(status.get("generation"), str)
                or (
                    status["generation"]
                    and GENERATION.fullmatch(status["generation"]) is None
                )
                or type(status.get("segment_seconds")) is not int
                or not 1 <= status["segment_seconds"] <= 3
                or type(status.get("segment_count")) is not int
                or not 3 <= status["segment_count"] <= 10
                or type(status.get("buffer_segments")) is not int
                or not 0 <= status["buffer_segments"] <= 32
                or type(status.get("buffer_bytes")) is not int
                or not 0 <= status["buffer_bytes"] <= 16 * 1024 * 1024
                or (status["ready"] and not status["generation"])
                or status.get("last_error", "")
                not in (
                    "",
                    "starting",
                    "source_unavailable",
                    "incompatible_media",
                    "segment_too_large",
                    "buffer_limit_exceeded",
                )
            ):
                raise BackendError("invalid_app_contract")
            return {
                key: status.get(key)
                for key in (
                    "api_version",
                    "generation",
                    "ready",
                    "running",
                    "segment_seconds",
                    "segment_count",
                    "buffer_segments",
                    "buffer_bytes",
                    "last_error",
                )
            }
        except ValueError, TypeError:
            raise BackendError("invalid_app_contract") from None


def rewrite_playlist(body: bytes, filename: str, signed_url) -> str:
    """Allow only this contract's tags/relative children; sign every media URL."""
    try:
        lines = body.decode("ascii").splitlines()
    except UnicodeError:
        raise BackendError("invalid_playlist") from None
    if not lines or lines[0] != "#EXTM3U":
        raise BackendError("invalid_playlist")
    result = []
    children = 0
    for line in lines:
        if line in ("#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"):
            result.append(line)
        elif filename == "master.m3u8" and re.fullmatch(
            r'#EXT-X-STREAM-INF:BANDWIDTH=[0-9]{1,9},CODECS="avc1\.[a-f0-9]{6},'
            r'mp4a\.40\.2",RESOLUTION=[0-9]{1,4}x[0-9]{1,4}',
            line,
        ):
            result.append(line)
        elif filename == "stream.m3u8" and re.fullmatch(
            r"#EXT-X-(TARGETDURATION:[1-9][0-9]?|MEDIA-SEQUENCE:[0-9]{1,20})", line
        ):
            result.append(line)
        elif filename == "stream.m3u8" and re.fullmatch(
            r"#EXTINF:[0-9]{1,2}\.[0-9]{6},", line
        ):
            result.append(line)
        elif (filename == "master.m3u8" and line == "stream.m3u8") or (
            filename == "stream.m3u8" and SEGMENT_NAME.fullmatch(line)
        ):
            children += 1
            result.append(signed_url(line))
        else:
            raise BackendError("invalid_playlist")
    if children < 1 or children > (1 if filename == "master.m3u8" else 10):
        raise BackendError("invalid_playlist")
    return "\n".join(result) + "\n"
