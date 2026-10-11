"""Assert the actual generated app pipeline's media contract using ffprobe JSON."""
import json
import sys
from fractions import Fraction

with open(sys.argv[1], encoding="utf-8") as stream:
    result = json.load(stream)
video = next(s for s in result["streams"] if s["codec_type"] == "video")
audio = next(s for s in result["streams"] if s["codec_type"] == "audio")
assert (video["codec_name"], video["profile"], video["width"], video["height"], video["level"]) == ("h264", "Main", 1280, 720, 31), video
assert Fraction(video["r_frame_rate"]) == 15, video
assert audio["codec_name"] == "aac", audio
frames = [f for f in result["frames"] if f["media_type"] == "video"]
assert len(frames) >= 25, "Too few decoded frames"
assert all(f["pict_type"] != "B" for f in frames), "Unexpected frame reordering"
keyframes = [float(f["best_effort_timestamp_time"]) for f in frames if f["key_frame"]]
assert len(keyframes) >= 2, "Keyframe cadence cannot be checked"
assert all(0.9 <= right - left <= 1.1 for left, right in zip(keyframes, keyframes[1:])), keyframes
print("Verified H.264 Main/3.1, 1280x720, AAC, 15 fps, one-second GOP, no B-frames")
