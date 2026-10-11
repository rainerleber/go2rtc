# Home Assistant app: go2rtc Chainguard

## Installation

Add this repository to **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc Chainguard** and enter these settings on the Configuration tab:

- **Camera address:** Reolink hostname or IP address, without `rtsp://` or a path
- **Camera username:** a dedicated Reolink live-view-only user
- **Camera password:** the password for that user
- **Source stream:** `sub` is recommended for fast startup on an Echo Show

The app generates `/config/go2rtc.yaml` in its private configuration directory
with mode 0600. Its API and RTSP listeners are fixed to loopback, WebRTC is
disabled, and the Alexa-compatible stream is transcoded automatically.
The transcoded stream stays preloaded because Echo Show accepts only a short
startup delay. This uses continuous CPU while keeping camera credentials and
all listeners local to the app.

The corresponding Home Assistant Generic Camera stream source is:

```text
rtsp://127.0.0.1:8554/reolink_haustuer_alexa
```

Expose only that Generic Camera entity to Alexa.

## Security notes

- Use a dedicated Reolink account with live-view permission only.
- The password field is masked in the UI. Home Assistant administrators remain
  a trust boundary because the Supervisor and the app must provide the secret
  to the camera connection.
- The app has no access to Home Assistant's configuration or Supervisor API.
- API and RTSP listeners are fixed to `127.0.0.1` and no ports are forwarded.
- The image runs without privileged mode and has no host filesystem access.
- The runtime contains go2rtc and Wolfi's FFmpeg 9 package. It does not include
  Python or hardware acceleration; Wolfi Base does include BusyBox and APK.

## Updates and rollback

The image is rebuilt weekly and after relevant source changes. The workflow
publishes immutable `YYYY.MM.BUILD` CalVer tags and updates this app's version
only after the multi-architecture image was pushed successfully.

To roll back, select an earlier commit of this repository as an App Store
repository branch, or restore the app from a Home Assistant backup.
