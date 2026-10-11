# Home Assistant application runtime

This package reads the generated private app configuration, initializes logging,
and supplies build metadata. The binary always initializes only the local API,
streams, RTSP, exec and FFmpeg pipeline; there is no configurable protocol-module
catalog or embedded website.

Supervisor options are the supported user configuration. The native `-config`
argument remains for the app entrypoint and isolated synthetic runtime tests;
it does not enable removed upstream features. See
[the Home Assistant app guide](../../home-assistant/DOCS.md) for settings,
permissions, diagnostics and rollback.
