"""Bounded, vendor-independent H.264/AAC remuxing and legacy HLS playlists.

This module has no HA dependency. No decoded frames or camera recordings are
written to disk. Each segment has its own PAT/PMT and decoder configuration;
transport continuity counters are preserved across separately flushed muxers.
"""

import math
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import av

from .const import MAX_BUFFER_BYTES, MAX_SEGMENT_BYTES, STALE_SECONDS


class MediaError(Exception):
    """An intentionally credential-free, machine-readable error code."""


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    video_codec: str


@dataclass(frozen=True)
class Segment:
    sequence: int
    duration: float
    data: bytes
    discontinuity: bool
    created: float


class LimitedBuffer(BytesIO):
    """Reject unexpectedly large GOPs before they exhaust HA memory."""

    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > MAX_SEGMENT_BYTES:
            raise MediaError("segment_too_large")
        return super().write(data)


class SegmentRing:
    """Event-loop-owned buffer with monotonic sequence and discontinuity state."""

    def __init__(self, count: int, segment_seconds: float) -> None:
        self.count = count
        self.target_duration = math.ceil(segment_seconds)
        self.segments: deque[Segment] = deque()
        self.bytes = 0
        self.next_sequence = 0
        self.discontinuity_sequence = 0
        self.info: MediaInfo | None = None

    @property
    def ready(self) -> bool:
        return bool(self.segments) and (
            time.monotonic() - self.segments[-1].created <= STALE_SECONDS
        )

    def append(
        self, data: bytes, duration: float, discontinuity: bool, info: MediaInfo
    ) -> None:
        if not data or len(data) > MAX_SEGMENT_BYTES:
            raise MediaError("segment_too_large")
        if not 0 < duration < self.target_duration + 0.5:
            raise MediaError("keyframe_interval_too_long")
        previous_info = self.info
        self.info = info
        self.segments.append(
            Segment(self.next_sequence, duration, data, discontinuity, time.monotonic())
        )
        self.next_sequence += 1
        self.bytes += len(data)
        while len(self.segments) > self.count or self.bytes > MAX_BUFFER_BYTES:
            remaining_duration = sum(s.duration for s in list(self.segments)[1:])
            # RFC 8216: eviction must not shorten a live window below three
            # target durations. Keep an extra segment for small timestamp jitter.
            if remaining_duration < 3 * self.target_duration:
                if self.bytes > MAX_BUFFER_BYTES:
                    rejected = self.segments.pop()
                    self.bytes -= len(rejected.data)
                    self.info = previous_info
                    raise MediaError("buffer_limit_exceeded")
                break
            old = self.segments.popleft()
            self.bytes -= len(old.data)
            self.discontinuity_sequence += int(old.discontinuity)

    def clear(self) -> None:
        # Keep sequences monotonic so a recovering client cannot fetch a new
        # segment under the URL of an old segment.
        self.discontinuity_sequence += sum(s.discontinuity for s in self.segments)
        self.segments.clear()
        self.bytes = 0
        self.info = None

    def get(self, sequence: int) -> Segment | None:
        return next((s for s in self.segments if s.sequence == sequence), None)

    def master(self, playlist_url: str) -> str:
        if not self.ready or self.info is None:
            raise MediaError("stream_not_ready")
        duration = sum(s.duration for s in self.segments)
        bandwidth = max(400_000, math.ceil(self.bytes * 8 / duration * 1.5))
        return (
            "#EXTM3U\n#EXT-X-VERSION:3\n"
            f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
            f"RESOLUTION={self.info.width}x{self.info.height},"
            f'CODECS="{self.info.video_codec},mp4a.40.2"\n{playlist_url}\n'
        )

    def playlist(self, segment_url: Callable[[int], str]) -> str:
        if not self.ready:
            raise MediaError("stream_not_ready")
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{self.target_duration}",
            f"#EXT-X-MEDIA-SEQUENCE:{self.segments[0].sequence}",
            f"#EXT-X-DISCONTINUITY-SEQUENCE:{self.discontinuity_sequence}",
        ]
        for segment in self.segments:
            if segment.discontinuity:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.extend(
                (f"#EXTINF:{segment.duration:.6f},", segment_url(segment.sequence))
            )
        return "\n".join(lines) + "\n"


def h264_codec_string(extradata: bytes) -> str:
    """Read profile/compatibility/level from AVC or Annex B SPS metadata."""
    if len(extradata) >= 4 and extradata[0] == 1:
        return f"avc1.{extradata[1:4].hex()}"
    for nal in re.split(b"\x00\x00\x00?\x01", extradata):
        if len(nal) >= 4 and nal[0] & 0x1F == 7:
            return f"avc1.{nal[1:4].hex()}"
    raise MediaError("missing_h264_configuration")


class TransportCounters:
    """Preserve MPEG-TS payload continuity counters across segment muxers."""

    def __init__(self) -> None:
        self.last: dict[int, int] = {}

    def rewrite(self, data: bytes) -> bytes:
        if len(data) % 188:
            raise MediaError("invalid_transport_stream")
        result = bytearray(data)
        for offset in range(0, len(result), 188):
            if result[offset] != 0x47:
                raise MediaError("invalid_transport_stream")
            pid = ((result[offset + 1] & 0x1F) << 8) | result[offset + 2]
            control = result[offset + 3] >> 4 & 3
            if control == 0:
                raise MediaError("invalid_transport_stream")
            previous = self.last.get(pid, -1)
            counter = (previous + 1) % 16 if control & 1 else max(previous, 0)
            self.last[pid] = counter
            result[offset + 3] = result[offset + 3] & 0xF0 | counter
        return bytes(result)


class Remuxer:
    """Copy compressed packets; close and publish only complete keyframe GOPs."""

    def __init__(
        self,
        input_container: Any,
        segment_seconds: float,
        publish: Callable[[bytes, float, bool, MediaInfo], None],
    ) -> None:
        videos = input_container.streams.video
        audios = input_container.streams.audio
        if not videos or videos[0].codec_context.name != "h264":
            raise MediaError("h264_required")
        if not audios or audios[0].codec_context.name != "aac":
            raise MediaError("aac_required")
        self.video = videos[0]
        self.audio = audios[0]
        # Alexa's HA adapter advertises AAC-LC, not HE-AAC.
        if self.audio.codec_context.profile not in (None, "LC"):
            raise MediaError("aac_lc_required")
        self.info = MediaInfo(
            self.video.codec_context.width,
            self.video.codec_context.height,
            h264_codec_string(self.video.codec_context.extradata or b""),
        )
        self.segment_seconds = segment_seconds
        self.max_duration = math.ceil(segment_seconds) + 0.49
        self.publish = publish
        self.counters = TransportCounters()
        self.output: Any = None
        self.buffer: LimitedBuffer | None = None
        self.mapping: dict[int, Any] = {}
        self.start_pts: float | None = None
        self.end_pts = 0.0
        self.first_segment = True

    def _open(self, pts: float) -> None:
        self.buffer = LimitedBuffer()
        self.output = av.open(
            self.buffer,
            mode="w",
            format="mpegts",
            options={
                "mpegts_copyts": "1",
                "mpegts_flags": "+resend_headers",
                "avoid_negative_ts": "disabled",
                "flush_packets": "1",
            },
        )
        self.mapping = {
            stream.index: self.output.add_stream_from_template(stream)
            for stream in (self.video, self.audio)
        }
        self.start_pts = pts
        self.end_pts = pts

    def _finish(self, duration: float, *, publish: bool) -> None:
        if self.output is None or self.buffer is None:
            return
        try:
            self.output.close()
            if publish and duration > 0:
                self.publish(
                    self.counters.rewrite(self.buffer.getvalue()),
                    duration,
                    self.first_segment,
                    self.info,
                )
                self.first_segment = False
        finally:
            self.output = None
            self.buffer = None

    def feed(self, packet: Any) -> None:
        if not packet.size or packet.pts is None:
            return
        source_index = packet.stream.index
        if source_index not in (self.video.index, self.audio.index):
            return
        if source_index == self.video.index:
            pts = float(packet.pts * packet.time_base)
            if self.start_pts is None:
                if not packet.is_keyframe:
                    return
                self._open(pts)
            else:
                elapsed = pts - self.start_pts
                if elapsed < -0.5:
                    raise MediaError("timestamp_discontinuity")
                if elapsed > self.max_duration:
                    raise MediaError("keyframe_interval_too_long")
                if packet.is_keyframe and elapsed >= self.segment_seconds - 0.001:
                    self._finish(elapsed, publish=True)
                    self._open(pts)
            self.end_pts = max(
                self.end_pts, pts + float(packet.duration * packet.time_base)
            )
        if self.output is not None:
            packet.stream = self.mapping[source_index]
            self.output.mux(packet)

    def close(self, *, publish: bool = False) -> None:
        duration = self.end_pts - (self.start_pts or 0.0)
        self._finish(duration, publish=publish)
