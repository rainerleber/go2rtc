# Home Assistant app: go2rtc Chainguard

## Installation

Add this repository to **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc Chainguard**, but do not start it before creating the
configuration described below.

## Configuration

Set the complete YAML in `config` and the secret separately in the masked
`camera_password` field. The YAML must use `${CAMERA_PASSWORD}` at the password
position. On every start the app writes `go2rtc.yaml` with mode 0600 inside its
private `/config` directory. Use a dedicated Reolink account that has live-view
permission only.

This example binds every server to loopback and disables WebRTC because the
Alexa proxy only needs local RTSP. Replace the placeholders locally:

```yaml
app:
  modules: [api, ffmpeg, rtsp]

api:
  listen: "127.0.0.1:1984"

rtsp:
  listen: "127.0.0.1:8554"

webrtc:
  listen: ""

streams:
  reolink_haustuer:
    - rtsp://VIEW_ONLY_USER:${CAMERA_PASSWORD}@CAMERA_ADDRESS:554/h264Preview_01_sub

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

- Use a dedicated Reolink account with live-view permission only.
- The app has no access to Home Assistant's configuration or Supervisor API.
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
