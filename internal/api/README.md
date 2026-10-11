# Local diagnosis API

The Home Assistant app binds this API to `127.0.0.1:1984`. It has no web UI,
static file server, HLS endpoint or WebRTC endpoint. Home Assistant consumes the
separate local RTSP listener and provides camera playback itself.

`GET /api/preload` reports preload intent and status. `GET /api/streams`
reports attached producers and consumers. These are administrative diagnosis
interfaces, not proof that a viewer displayed a frame. Responses and logs may
contain camera credentials: do not publish them or expose the API on the LAN.

App options and permissions are documented in
[the Home Assistant app guide](../../home-assistant/DOCS.md).
