#!/usr/bin/env bash
# Run on an isolated Linux Docker host. No real cameras or credentials are used.
set -euo pipefail
image="${1:-go2rtc-chainguard:test}"
task_dir="$(mktemp -d)"
app_name="go2rtc-app-test-$$"
source_name="go2rtc-source-test-$$"
cleanup() {
  docker rm -f "$app_name" "$source_name" >/dev/null 2>&1 || true
  # Only the explicitly created temporary test directory is removed.
  rm -rf -- "$task_dir"
}
trap cleanup EXIT
mkdir -p "$task_dir/data" "$task_dir/config" "$task_dir/results"
await_status() {
  local want="$1"
  for ((attempt=0; attempt<40; attempt++)); do
    if curl -fsS http://127.0.0.1:1984/api/preload 2>/dev/null |
      jq -e --arg want "$want" '.test_output.status == $want' >/dev/null; then return; fi
    sleep 1
  done
  docker logs "$app_name"
  return 1
}
for shape in landscape wide portrait; do
  echo "Testing generated app output: $shape"
  jq --arg path "/$shape" '.camera_path = $path' testdata/hassaddon/options.json > "$task_dir/data/options.json"
  docker run -d --name "$app_name" --network host \
    -v "$task_dir/data:/data:ro" -v "$task_dir/config:/config" "$image" >/dev/null
  if [[ "$shape" == landscape ]]; then
    # Prove recovery when the camera is unavailable during app startup.
    await_status retrying
    docker run -d --name "$source_name" --network host \
      -v "$PWD/testdata/hassaddon/source.json:/source.json:ro" \
      "$image" -config /source.json >/dev/null
  fi
  await_status active
  # HA owns HLS and the user interface; upstream web and streaming endpoints
  # must not accidentally reappear in this HA-only binary.
  for path in / /index.html /config.html /api/webrtc /api/stream.m3u8; do
    status="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:1984$path")"
    [[ "$status" == 404 ]] || { echo "Unexpected endpoint $path: $status"; exit 1; }
  done
  # Capture a fixed number of video frames. A wall-clock -t cutoff is flaky
  # when audio starts before the first decodable RTSP video keyframe.
  timeout 30s docker run --rm --network host -v "$task_dir/results:/results" \
    --entrypoint /usr/bin/ffmpeg "$image" -hide_banner -loglevel error \
    -rtsp_transport tcp -analyzeduration 2000000 -probesize 1048576 \
    -i rtsp://127.0.0.1:8554/test_output -map 0:v:0 -map 0:a:0 \
    -frames:v 60 -c copy -y "/results/$shape.mkv"
  docker run --rm -v "$task_dir/results:/results:ro" \
    --entrypoint /usr/bin/ffprobe "$image" -v error -show_streams -show_frames \
    -of json "/results/$shape.mkv" > "$task_dir/results/$shape.json"
  python3 scripts/verify-app-media.py "$task_dir/results/$shape.json"
  docker rm -f "$app_name" >/dev/null
done
