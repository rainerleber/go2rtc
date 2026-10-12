# Changelog

## 2026.10.30

- Start HLS media sequences at zero for each worker generation instead of
  using epoch microseconds, preserving compatibility with older 32-bit parsers.
- Keep generation-scoped playback and upload protection when segment filenames
  are reused after reconnects. Add regression and real-media sequence tests.
- No App settings, privileges or HA bridge code change; only the App needs
  updating. Sustained playback must still be verified on the actual Echo.

## Next

- Use the plain `go2rtc` app name and functional descriptions, without branding
  the app after its base-image provider. Keep existing app and registry
  identifiers stable so installations retain their configuration and data.

- Select H.264 Level 3.1 for 720p and Level 4.0 for larger validated outputs
  instead of unnecessarily requiring a Level 4.1 decoder.

- Require an explicit video track instead of silently accepting FFmpeg's
  audio-only automatic selection; audio remains optional for silent cameras.
- Make runtime capture deterministic with explicit tracks, sufficient probe
  time and fixed video-frame counts under a timeout.

- Keep upgrade defaults empty for path/names so Supervisor's default merge
  cannot override existing source paths or stream names; test the real merge.

- Accept vendor-independent RTSP paths, ports and stream names, with automatic
  migration of existing Reolink configurations.
- Add structured output mode, preload, resolution, frame-rate, keyframe and
  bitrate options, documented and translated in English and German.
- Retry failed preloads independently with bounded backoff and cancellation.
- Reduce compatibility GOP to one second, bound local probing and disable
  frame reordering; preserve arbitrary source aspect ratios with scale/pad.
- Add retry/cancellation, configuration/security tests and a real container
  pipeline test for landscape, widescreen and portrait sources.
- Correct camera account guidance: a new user is optional and device roles
  are not necessarily limited to live view.

- Keep the 1280x720 H.264/AAC Alexa transcode preloaded so Echo Show requests
  do not time out while FFmpeg and the camera stream start.
- Feed the Alexa transcode from the shared local proxy to avoid a second
  camera connection.
- Enable the go2rtc exec handler required by generated FFmpeg streams.
- Replace the raw YAML text area with labelled camera address, username,
  password and stream fields.
- Generate the private loopback-only go2rtc configuration inside the app and
  safely URL-escape camera credentials.
- Shorten published versions to the `YYYY.MM.BUILD` CalVer format.
- Keep access limited to the app-specific configuration directory; no Home
  Assistant configuration mount or Supervisor API token is granted.

## 2026.10.10.0

- Initial Home Assistant app metadata for the independently built image.
- Limited mounts to the app-specific configuration directory.
- Added a loopback-only Reolink-to-Alexa proxy example.
- Updated the source and validation pipeline to Go 1.27.2.
- Migrated the Go module namespace to `github.com/rainerleber/go2rtc`.
- Replaced the legacy image, GitHub Pages, examples, scripts, and unused code
  with one verified container image pipeline.
