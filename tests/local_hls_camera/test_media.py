"""Real PyAV/FFmpeg remuxing, standalone segments and bounded playlists."""

import time
from io import BytesIO

import av
import pytest

from custom_components.local_hls_camera.const import MAX_SEGMENT_BYTES
from custom_components.local_hls_camera.media import (
    LimitedBuffer,
    MediaError,
    MediaInfo,
    Remuxer,
    SegmentRing,
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
