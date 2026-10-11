# Changelog

## Next

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

- Initial Home Assistant app metadata for the Chainguard/Wolfi-based image.
- Limited mounts to the app-specific configuration directory.
- Added a loopback-only Reolink-to-Alexa proxy example.
- Updated the source and validation pipeline to Go 1.27.2.
- Migrated the Go module namespace to `github.com/rainerleber/go2rtc`.
- Replaced the legacy image, GitHub Pages, examples, scripts, and unused code
  with one verified Chainguard/Wolfi image pipeline.
