# go2rtc

This Home Assistant app provides a local RTSP camera proxy and an optional,
preloaded H.264/AAC compatibility stream. Its container is independently built
and published by this repository's GitHub Actions workflow.

The app receives only its own configuration directory at `/config`. It does not
receive the Home Assistant configuration directory, a Supervisor API token,
devices, or privileged container access. Camera settings are entered through
individual app options; the app generates its private go2rtc configuration.

See [DOCS.md](DOCS.md) for installation and secure configuration.
