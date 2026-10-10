# go2rtc Chainguard

This Home Assistant app runs the fork's independently built go2rtc image. It
uses signed Chainguard Go and Wolfi images as its build and runtime foundation.

The app receives its own configuration directory at `/config` and read-only
access to the Home Assistant configuration at `/homeassistant`. The latter is
used to import an existing Reolink integration without copying its credentials
into `go2rtc.yaml`. It does not receive a Supervisor API token, devices, or
privileged container access.

See [DOCS.md](DOCS.md) for installation and secure configuration.
