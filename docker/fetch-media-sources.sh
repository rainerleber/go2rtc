#!/usr/bin/env bash
set -euo pipefail

readonly ffmpeg_version="9.0.2"
readonly ffmpeg_sha256="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
readonly x264_commit="b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
readonly x264_sha256="cd71a7515b0e9a012e1ac9b1f8415bebcaf6fc97d4db32286642ac4c0fbe24f9"

readonly output_dir=".build-sources"
readonly temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

curl --fail --silent --show-error --location \
  "https://ffmpeg.org/releases/ffmpeg-${ffmpeg_version}.tar.xz" \
  --output "${temporary_dir}/ffmpeg.tar.xz"
curl --fail --silent --show-error --location \
  "https://code.videolan.org/videolan/x264/-/archive/${x264_commit}/x264-${x264_commit}.tar.gz" \
  --output "${temporary_dir}/x264.tar.gz"

printf '%s  %s\n' "$ffmpeg_sha256" "${temporary_dir}/ffmpeg.tar.xz" | sha256sum --check --strict
printf '%s  %s\n' "$x264_sha256" "${temporary_dir}/x264.tar.gz" | sha256sum --check --strict

rm -rf "${output_dir}/ffmpeg" "${output_dir}/x264"
mkdir -p "${output_dir}/ffmpeg" "${output_dir}/x264"
tar --extract --file "${temporary_dir}/ffmpeg.tar.xz" --strip-components=1 --directory "${output_dir}/ffmpeg"
tar --extract --file "${temporary_dir}/x264.tar.gz" --strip-components=1 --directory "${output_dir}/x264"
