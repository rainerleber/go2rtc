# Home Assistant compatibility encoder

The app generates a constrained FFmpeg source from structured Supervisor options.
FFmpeg connects to the shared loopback RTSP source, so camera credentials are not
passed in its command line. H.264 normalization, optional AAC audio, aspect-ratio
preserving scaling/padding and preload are covered by unit and synthetic runtime
tests.

Native FFmpeg parsing and test sources remain implementation details. The app
exposes no arbitrary shell arguments, file/media mounts, device access or
hardware-acceleration controls. Supported settings are documented in
[the Home Assistant app guide](../../home-assistant/DOCS.md).
