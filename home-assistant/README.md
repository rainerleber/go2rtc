# go2rtc Chainguard

This Home Assistant app runs the fork's independently built go2rtc image. It
uses signed Chainguard Go and Wolfi images as its build and runtime foundation.

The app receives only its own configuration directory at `/config`. It does not
receive the Home Assistant configuration directory, a Supervisor API token,
devices, or privileged container access. Camera settings are entered through
individual app options; the app generates its private go2rtc configuration.

See [DOCS.md](DOCS.md) for installation and secure configuration.
