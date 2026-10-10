# Home Assistant app: go2rtc Chainguard

## Installation

Add this repository to **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc Chainguard**, but do not start it before creating the
configuration described below.

## Configuration

Create `go2rtc.yaml` in this app's configuration directory. Home Assistant
mounts that private directory at `/config` inside the app. The app can import
an existing Reolink integration from Home Assistant's read-only configuration
mount, so camera credentials do not need to be copied into this file.

This example binds every server to loopback and disables WebRTC because the
Alexa proxy only needs local RTSP. Replace the placeholders locally:

```yaml
app:
  modules: [api, ffmpeg, hass, rtsp]

api:
  listen: "127.0.0.1:1984"

rtsp:
  listen: "127.0.0.1:8554"

webrtc:
  listen: ""

streams:
  reolink_haustuer:
    - hass:Front Door

  reolink_haustuer_alexa:
    - >-
      ffmpeg:reolink_haustuer#video=h264#audio=aac
      #raw=-vf scale=960:720,pad=1280:720:160:0:black
```

The corresponding Home Assistant Generic Camera stream source is:

```text
rtsp://127.0.0.1:8554/reolink_haustuer_alexa
```

Expose only that Generic Camera entity to Alexa.

## Security notes

- The imported Reolink account should have live-view permission only.
- Home Assistant's configuration is mounted read-only and is never modified.
- Keep API and RTSP listeners on `127.0.0.1`; do not forward their ports.
- The image runs without privileged mode and has no host filesystem access.
- The runtime contains go2rtc and Wolfi's FFmpeg 9 package. It does not include
  Python or hardware acceleration; Wolfi Base does include BusyBox and APK.
- Camera URLs contain credentials. Treat `go2rtc.yaml` and app logs as secrets.
- go2rtc deliberately supports FFmpeg and external command execution. Do not
  expose its API to untrusted networks and do not paste untrusted configuration.

## Updates and rollback

The image is rebuilt weekly and after relevant source changes. The workflow
publishes immutable date/run tags and updates this app's version only after the
multi-architecture image was pushed successfully.

To roll back, select an earlier commit of this repository as an App Store
repository branch, or restore the app from a Home Assistant backup.
