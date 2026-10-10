# go2rtc Chainguard

This Home Assistant app runs the fork's independently built go2rtc image. It
uses signed Chainguard Go and Wolfi images as its build and runtime foundation.

The app receives only its own configuration directory at `/config`. It does not
receive the Home Assistant configuration directory, a Supervisor API token,
devices, or privileged container access. The full YAML is supplied as an app
option, while the camera password remains a separate masked `password` option.

See [DOCS.md](DOCS.md) for installation and secure configuration.
