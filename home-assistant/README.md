# go2rtc Chainguard

This Home Assistant app runs the fork's independently built go2rtc image. It
uses signed Chainguard Go and Wolfi images as its build and runtime foundation.

The app is intentionally minimal: it receives only its own app configuration
directory at `/config` and uses host networking for local RTSP access. It does
not receive the Home Assistant configuration directory, Supervisor API token,
devices, or privileged container access.

See [DOCS.md](DOCS.md) for installation and secure configuration.
