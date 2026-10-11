"""Real PyAV/FFmpeg remuxing, standalone segments and bounded playlists."""

import time
from fractions import Fraction
from io import BytesIO
from types import SimpleNamespace

import av
import pytest

from custom_components.local_hls_camera.const import MAX_SEGMENT_BYTES
from custom_components.local_hls_camera.media import (
    LimitedBuffer,
    MediaError,
    MediaInfo,
    Remuxer,
    SegmentRing,
    TimestampGuard,
    TransportCounters,
    h264_codec_string,
)


def make_segments(path):
    result = []
    with av.open(str(path)) as source:
        remuxer = Remuxer(source, 1, lambda *args: result.append(args))
        for packet in source.demux(remuxer.video, remuxer.audio):
            remuxer.feed(packet)
        remuxer.close(publish=True)
    return result


def test_each_segment_decodes_without_an_initialization_file(synthetic_video):
    segments = make_segments(synthetic_video)
    assert len(segments) == 8
    last_pts = None
    for data, duration, discontinuity, info in segments:
        assert 0.9 <= duration <= 1.1
        assert info == MediaInfo(320, 180, "avc1.4d401f")
        assert len(data) % 188 == 0
        pids = {
            ((data[i + 1] & 31) << 8) | data[i + 2] for i in range(0, len(data), 188)
        }
        assert 0 in pids  # PAT
        assert 4096 in pids  # PMT
        with av.open(BytesIO(data), format="mpegts") as decoded:
            assert decoded.streams.video[0].codec_context.name == "h264"
            assert decoded.streams.audio[0].codec_context.name == "aac"
            frames = list(decoded.decode(video=0))
            assert len(frames) == 15
            assert frames[0].key_frame
            pts = frames[0].pts * frames[0].time_base
            if last_pts is not None:
                assert pts > last_pts
            last_pts = pts
    assert [s[2] for s in segments] == [True] + [False] * 7


@pytest.mark.parametrize("track", ["audio", "video"])
@pytest.mark.parametrize("offset", [0, -227])
def test_duplicate_or_late_packets_do_not_interrupt_remux(
    synthetic_video, track, offset
):
    segments = []
    injected = False
    with av.open(str(synthetic_video)) as source:
        remuxer = Remuxer(source, 1, lambda *args: segments.append(args))
        for packet in source.demux(remuxer.video, remuxer.audio):
            replay = None
            if (
                not injected
                and packet.size
                and packet.pts is not None
                and packet.dts is not None
                and packet.stream.type == track
                and packet.pts * packet.time_base > 1.5
            ):
                # Preserve the input time base: mux() rebases the original packet.
                replay = av.Packet(bytes(packet))
                replay.stream = packet.stream
                replay.time_base = packet.time_base
                replay.pts = packet.pts + offset
                replay.dts = packet.dts + offset
                replay.duration = packet.duration
                injected = True
            remuxer.feed(packet)
            if replay is not None:
                remuxer.feed(replay)
        remuxer.close(publish=True)
    assert injected
    assert remuxer.timestamps.dropped_packets == 1
    assert len(segments) == 8
    for data, *_ in segments:
        with av.open(BytesIO(data), format="mpegts") as decoded:
            frames = list(decoded.decode(video=0))
            assert len(frames) == 15
            assert frames[0].key_frame
        with av.open(BytesIO(data), format="mpegts") as decoded:
            assert list(decoded.decode(audio=0))


def timestamp_packet(index, dts, time_base=Fraction(1, 16000)):
    return SimpleNamespace(
        stream=SimpleNamespace(index=index), pts=dts, dts=dts, time_base=time_base
    )


def test_timestamp_guard_uses_per_track_rational_input_times():
    guard = TimestampGuard()
    assert guard.accept(timestamp_packet(0, 90000, Fraction(1, 90000)))
    assert guard.accept(timestamp_packet(1, 16000))
    # Changing time bases must not make a duplicate look newer.
    assert not guard.accept(timestamp_packet(1, 90000, Fraction(1, 90000)))
    assert not guard.accept(timestamp_packet(1, 16000 - 227))
    assert guard.accept(timestamp_packet(1, 17024))
    assert guard.accept(timestamp_packet(0, 96000, Fraction(1, 90000)))
    assert guard.dropped_packets == 2


@pytest.mark.parametrize("next_dts", [0, 32 * 16000])
def test_timestamp_reset_or_large_gap_requests_clean_reconnect(next_dts):
    guard = TimestampGuard()
    assert guard.accept(timestamp_packet(1, 16000))
    with pytest.raises(MediaError, match="^timestamp_discontinuity$"):
        guard.accept(timestamp_packet(1, next_dts))
    assert guard.last[1] == 1


def test_missing_timestamps_are_bounded_per_track():
    guard = TimestampGuard()
    for _ in range(6):
        assert not guard.accept(timestamp_packet(1, None))
        assert guard.accept(timestamp_packet(0, _ + 1))
    with pytest.raises(MediaError, match="^missing_packet_timestamps$"):
        guard.accept(timestamp_packet(1, None))


@pytest.mark.parametrize("time_base", [None, Fraction(0), Fraction(-1)])
def test_invalid_packet_clock_is_rejected(time_base):
    with pytest.raises(MediaError, match="^invalid_packet_time_base$"):
        TimestampGuard().accept(timestamp_packet(1, 10, time_base))


def test_transport_continuity_across_segments(synthetic_video):
    last = {}
    for data, *_ in make_segments(synthetic_video):
        for offset in range(0, len(data), 188):
            pid = ((data[offset + 1] & 31) << 8) | data[offset + 2]
            control = data[offset + 3] >> 4 & 3
            counter = data[offset + 3] & 15
            if pid in last:
                assert counter == (last[pid] + int(bool(control & 1))) % 16
            last[pid] = counter


def test_sliding_playlist_sequence_and_discontinuity(synthetic_video):
    ring = SegmentRing(3, 1)
    for segment in make_segments(synthetic_video):
        ring.append(*segment)
    playlist = ring.playlist(lambda sequence: f"segment-{sequence}.ts?authSig=test")
    assert "#EXT-X-VERSION:3" in playlist
    assert "#EXT-X-TARGETDURATION:1" in playlist
    assert "#EXT-X-MEDIA-SEQUENCE:5" in playlist
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:1" in playlist
    assert "#EXT-X-MAP" not in playlist
    assert "#EXT-X-PART" not in playlist
    assert playlist.count("#EXTINF:") == 3
    master = ring.master("stream.m3u8?authSig=test")
    assert 'CODECS="avc1.4d401f,mp4a.40.2"' in master
    assert "RESOLUTION=320x180" in master
    assert ring.get(4) is None
    ring.clear()
    assert ring.next_sequence == 8
    assert ring.bytes == 0
    assert not ring.ready
    with pytest.raises(MediaError, match="stream_not_ready"):
        ring.playlist(str)


def test_limits_and_expired_media():
    info = MediaInfo(320, 180, "avc1.4d401f")
    ring = SegmentRing(10, 1)
    for _ in range(10):
        ring.append(b"x" * MAX_SEGMENT_BYTES, 1, False, info)
    assert len(ring.segments) == 4
    assert ring.bytes == 16 * 1024 * 1024
    with pytest.raises(MediaError, match="segment_too_large"):
        LimitedBuffer().write(b"x" * (MAX_SEGMENT_BYTES + 1))
    with pytest.raises(MediaError, match="keyframe_interval_too_long"):
        ring.append(b"x", 3, False, info)
    with pytest.raises(MediaError, match="invalid_transport_stream"):
        TransportCounters().rewrite(b"bad")
    old = ring.segments[-1]
    from dataclasses import replace

    ring.segments[-1] = replace(old, created=time.monotonic() - 6)
    assert not ring.ready


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (b"\x01\x4d\x40\x1f", "avc1.4d401f"),
        (b"\x00\x00\x00\x01\x67\x64\x00\x28", "avc1.640028"),
    ],
)
def test_codec_metadata(extra, expected):
    assert h264_codec_string(extra) == expected


def test_missing_codec_metadata_is_not_guessed():
    with pytest.raises(MediaError, match="missing_h264_configuration"):
        h264_codec_string(b"")


def test_live_window_preserved_with_timestamp_jitter():
    ring = SegmentRing(3, 1)
    info = MediaInfo(320, 180, "avc1.4d401f")
    for _ in range(10):
        ring.append(b"data", 0.9999, False, info)
    assert len(ring.segments) == 4
    assert sum(s.duration for s in ring.segments) >= 3 * ring.target_duration


def test_impossible_live_window_does_not_leave_an_oversized_buffer():
    ring = SegmentRing(3, 3)
    info = MediaInfo(320, 180, "avc1.4d401f")
    for _ in range(4):
        ring.append(b"x" * MAX_SEGMENT_BYTES, 1, False, info)
    with pytest.raises(MediaError, match="buffer_limit_exceeded"):
        ring.append(b"x" * MAX_SEGMENT_BYTES, 1, False, info)
    assert ring.bytes <= 16 * 1024 * 1024
