# Home Assistant app: go2rtc

## Function

This app accepts **one vendor-independent RTSP camera** and exposes two local
streams: the original source and a compatibility output. In `h264_aac` mode,
FFmpeg reads the shared local source, converts video to H.264 Main
and available audio to AAC, and preserves the image aspect ratio with black padding.
It handles 4:3, 16:9 and portrait images without vendor-specific geometry.
Video is mapped explicitly so incomplete startup metadata cannot silently select
an audio-only output. A source with no audio remains video-only; silence is not synthesized.
No raw shell/FFmpeg settings, cloud camera account, or browser workaround is needed.
This fork is limited to the Home Assistant app. It does not include the
upstream web UI, WebRTC, HomeKit, cloud providers or tunnel modules.
Home Assistant receives RTSP and produces its own HLS output for Alexa.
No file from the removed upstream `www` directory is needed for this path.

The compatibility output defaults to 1280x720 at 15 fps, 1500 kbit/s and one
keyframe per second. Short keyframe spacing reduces the wait for a decodable
frame and HLS segment boundaries. A `superfast`, `zerolatency` encoder with no
B-frames avoids frame reordering. Local FFmpeg input probing is bounded to
250 ms / 256 KiB. These settings improve startup but cannot eliminate Echo
Show, network, or Home Assistant HLS buffering.

The H.264 level is selected from the output geometry and frame rate: Level 3.1
for at most 3600 macroblocks / 108000 macroblocks per second (including 720p30),
otherwise Level 4.0 (up to the supported 1080p30). This avoids unnecessarily
requiring a Level 4.1 decoder. Dimensions are rounded up to 16x16 macroblocks.

With `preload: true`, the output remains connected even with no viewers.
This consumes continuous camera bandwidth and, when transcoding, CPU.
Unavailable sources retry independently after 1, 2, 4, 8, 16, then 30 seconds
(maximum); an offline camera at boot no longer permanently disables preloading.
Once connected, the normal producer reconnection mechanism handles outages.

## Installation

Add this repository to **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc**, enter the options below, save and start/restart
the app. Changes take effect on the next app restart.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `camera_address` | empty; required | Bare camera hostname, IPv4 or IPv6 address; no protocol/port/path. |
| `camera_port` | 554 | RTSP port, 1–65535. |
| `camera_path` | empty; required for new installs | Camera-specific absolute RTSP path, optionally including a query. No full URL or fragment. |
| `camera_username` | empty | Existing **local camera** account; empty only for an intentionally unauthenticated source. |
| `camera_password` | empty | Masked password; requires a username when nonempty. |
| `source_name` | empty → camera | Original local stream name. Letters, digits, underscore/hyphen, maximum 64 characters. |
| `output_name` | empty → camera_compatible | Output stream name; must differ from source name. |
| `output_mode` | h264_aac | Normalize to H.264/AAC. `passthrough` relays unchanged and does not launch FFmpeg. |
| `preload` | true | Keep output warm; false saves resources but increases cold-start latency. |
| `video_width` | 1280 | Even output width, 160–1920 pixels. |
| `video_height` | 720 | Even output height, 120–1080 pixels. |
| `video_fps` | 15 | Output frame rate, 1–30 fps. |
| `keyframe_seconds` | 1 | Keyframe interval, 1–5 seconds. GOP = fps × interval. |
| `video_bitrate_kbps` | 1500 | Target/maximum video bitrate, 128–8000 kbit/s; one-second encoder buffer. |
| `camera_stream` | legacy only | Old Reolink main/sub/ext selection, used only when camera_path is absent/empty. |

Video settings apply only to `h264_aac`. Passthrough cannot repair incompatible
codecs, profile, resolution or long camera keyframe intervals. With normalization,
use a lower-resolution camera substream to reduce decoding cost; upscaling does
not create detail. CPU cost rises with source/output resolution and fps.

Examples of **paths**, not credentials:

- Reolink: `/h264Preview_01_sub` (main/ext may be available).
- Cameras using a conventional first stream: `/stream1`.
- Other devices: use the RTSP path documented by their manufacturer.

Existing four-field app configurations migrate automatically: their Reolink
path and `reolink_haustuer` / `reolink_haustuer_alexa` names are retained.
Empty path/name defaults are intentional: Supervisor merges defaults into old
options during an update; nonempty defaults would overwrite migration choices.
New installations use generic names. When explicitly switching to the new
fields, enter both desired names to preserve existing consumers.
Do not rename stream names without updating their Home Assistant camera URLs.

## Home Assistant and Alexa

Create/configure a **Generic Camera** in Settings → Devices & services with:

```text
rtsp://127.0.0.1:8554/camera_compatible
```

Use your chosen output_name instead of camera_compatible, RTSP transport TCP,
and no camera username/password on this loopback connection. In that camera
entity's settings enable **Preload stream** as well. The app keeps RTSP/FFmpeg
warm; Home Assistant's separate preference keeps the HLS producer warm.
Expose only this Generic Camera entity to Alexa and use its Alexa name.

For the current HA Alexa HLS descriptor, 1280x720 H.264/AAC matches the advertised
format. Compatibility is not a guarantee that every Echo firmware will play it;
test on the actual device. See the
[HA camera-stream issue](https://github.com/home-assistant/core/issues/172245).
Amazon documents a maximum H.264 Level 4 for the listed Echo Show 15/21 models;
see [Echo Show codec specifications](https://developer.amazon.com/docs/device-specs/device-specifications-echo-show.html).

## Local camera accounts, including Reolink

RTSP authentication needs a camera credential when the source requires it.
A **new** user is not technically required: an existing account works. A dedicated
non-admin user is recommended to avoid granting camera administration to the app.
It is stored **on the camera**, not in HA, Alexa or a Reolink cloud account.

Reolink distinguishes older local User Management and newer Advanced Share UI.
For supported older devices, sign in as the original admin and open:

- Reolink App: Device settings → Advanced → User Management.
- Reolink desktop Client or local camera web UI: Device settings → System → User Management.

Newer firmware may instead show Share Device / Advanced Share. Do not assume
a cloud-sharing authorization code is an RTSP username/password. Check the
device-specific local stream authentication support.

Reolink's normal User role is **not strictly live-view-only**: playback and
other preview-page features may also be available. The app requires no admin
API permission and uses RTSP only, but that does not narrow the account's own
firmware permissions. See Reolink's
[account management](https://support.reolink.com/articles/360011355734-How-to-Add-Admin-User-Accounts-to-Reolink-Cameras/)
and [role comparison](https://support.reolink.com/articles/900000605423-Introduction-to-Admin-Account-and-User-Account/).
No new user is created by this app, and usernames/passwords do not change latency.

## Security and diagnostics

- Supervisor options generate private `/config/go2rtc.yaml` with mode 0600.
  This is JSON-compatible YAML; do not edit it manually because restart overwrites it.
- Password masking is not encryption. HA/Supervisor administrators and the app
  are trusted; they can access the credential required to connect.
- API and RTSP are enforced on `127.0.0.1:1984` and `127.0.0.1:8554`.
  No LAN ports or WebRTC listener are enabled. Other host-network processes remain
  part of this trust boundary.
- The app gets only its own configuration directory and host networking:
  no Supervisor/HA token, HA config mount, devices or privileged mode.
- Camera credentials are URL-escaped and stay out of FFmpeg command-line arguments.
  Configuration and logs should nevertheless be treated as sensitive.
- Runtime includes Wolfi FFmpeg 9, BusyBox and APK; no Python or hardware acceleration.

For administrators diagnosing on the HA host, `GET /api/preload` on the local
API reports `starting`, `retrying` or `active`. PUT requests register preload
intent asynchronously; success means accepted, not that a first frame arrived.
`active` means a consumer attached; it is not a continuous frame-freshness check.
Deleting/replacing a preload cancels pending retries and removes its consumer.
Do not expose the API merely to inspect it.

Measure both cold and warm **first decoded frame**, not just ffprobe's execution
time (which includes probing). An RTSP measurement does not equal Alexa screen
latency. Check source reachability/authentication, preload status, CPU and HA
HLS logs before increasing privileges or changing firewall rules.

When diagnosing Alexa, distinguish client requests from your own probes. A
successful master-playlist response without requests for the media playlist or
segments points to a failure before media decoding; more transcoding does not
establish that the playlist is usable by the client. Inspect HTTP content
encoding as well as HLS syntax. Older GStreamer clients can disable gzip
decoding by default ([upstream source](https://github.com/GStreamer/gst-plugins-good/blob/1.4.5/ext/soup/gstsouphttpsrc.c)).
A server that forces gzip can therefore be incompatible. This is a diagnostic
hypothesis until a controlled test confirms it on the actual Echo; a User-Agent
alone does not prove its full decoder configuration. HA owns these HTTP
responses, so this app's RTSP/FFmpeg settings cannot change their compression.

Successful segment downloads still do not prove playback. HA's fMP4 output
requires a separate initialization section, referenced by `EXT-X-MAP` (see
[HLS initialization requirements](https://www.rfc-editor.org/rfc/rfc8216.html#section-3.3)).
Check that the actual client fetches this resource as well as media segments.
If it downloads segments but never their initialization, investigate HLS
container/client compatibility before changing credentials or encoder settings.
The installed HA stream implementation still uses fMP4 when LL-HLS is disabled;
turning off LL-HLS alone does not produce legacy MPEG-TS segments.
Any HA-side compatibility experiment should be backed up, tested on the actual
device and rolled back if it does not fix playback. This app does not patch HA Core.

## Updates and rollback

The image is rebuilt weekly and after relevant source changes. The workflow
publishes immutable `YYYY.MM.BUILD` CalVer tags and updates this app's version
only after the multi-architecture image was pushed successfully.
Take an app backup before updating. To roll back, restore that app backup or
use an explicitly selected earlier app repository revision/image version.
