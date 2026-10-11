"""Exercise the generated container's HLS/JPEG API using synthetic media only."""

import json
import re
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

base = "http://127.0.0.1:1984/api/hls/v1/test_output/"


def fetch(name, limit, generation=None):
    query = "?" + urlencode({"generation": generation}) if generation else ""
    with urlopen(base + name + query, timeout=5) as response:
        assert response.status == 200
        data = response.read(limit + 1)
    assert len(data) <= limit
    return data


deadline = time.monotonic() + 40
while True:
    try:
        status = json.loads(fetch("status", 64 * 1024))
        if status["ready"]:
            break
    except OSError:
        pass
    assert time.monotonic() < deadline, "App HLS did not become ready"
    time.sleep(0.25)
assert status["api_version"] == 1
assert status["buffer_bytes"] <= 16 * 1024 * 1024
generation = status["generation"]
assert re.fullmatch(r"[a-f0-9]{32}", generation)
master = fetch("master.m3u8", 64 * 1024, generation).decode("ascii")
assert master.splitlines()[-1] == "stream.m3u8"
assert "avc1.4d401f,mp4a.40.2" in master and "RESOLUTION=1280x720" in master
playlist = fetch("stream.m3u8", 64 * 1024, generation).decode("ascii")
assert "EXT-X-MAP" not in playlist and "http:" not in playlist
name = playlist.splitlines()[-1]
assert re.fullmatch(r"segment-[0-9]{1,20}\.ts", name)
segment = fetch(name, 4 * 1024 * 1024, generation)
result = subprocess.run(
    [
        "docker",
        "run",
        "--rm",
        "-i",
        "--entrypoint",
        "/usr/bin/ffprobe",
        sys.argv[1],
        "-v",
        "error",
        "-f",
        "mpegts",
        "-show_streams",
        "-show_frames",
        "-of",
        "json",
        "pipe:0",
    ],
    input=segment,
    capture_output=True,
    check=True,
    timeout=20,
)
decoded = json.loads(result.stdout)
video = next(s for s in decoded["streams"] if s["codec_type"] == "video")
audio = next(s for s in decoded["streams"] if s["codec_type"] == "audio")
assert (
    video["codec_name"],
    video["profile"],
    video["level"],
    video["width"],
    video["height"],
) == ("h264", "Main", 31, 1280, 720)
assert audio["codec_name"] == "aac"
frames = [f for f in decoded["frames"] if f["media_type"] == "video"]
assert frames[0]["key_frame"] == 1 and len(frames) >= 14
image = fetch("snapshot.jpg", 2 * 1024 * 1024)
assert image.startswith(b"\xff\xd8")
subprocess.run(
    [
        "docker",
        "run",
        "--rm",
        "-i",
        "--entrypoint",
        "/usr/bin/ffmpeg",
        sys.argv[1],
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-i",
        "pipe:0",
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ],
    input=image,
    capture_output=True,
    check=True,
    timeout=20,
)
print("Verified RAM MPEG-TS HLS, actual 720p H.264/AAC metadata and decodable JPEG")
