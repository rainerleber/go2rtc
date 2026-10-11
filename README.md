# go2rtc Chainguard and Local HLS Camera for Home Assistant

This fork packages [go2rtc](https://github.com/AlexxIT/go2rtc) as a small,
independent Home Assistant app. It does not require the upstream app catalog
and does not consume the upstream container image.

The app accepts vendor-independent RTSP cameras and either relays their stream
unchanged or produces a warm H.264/AAC compatibility stream. Structured settings
control names, resolution, frame rate, bitrate and keyframe spacing. Scaling
preserves the source aspect ratio, including portrait doorbells. No Reolink
cloud or browser workaround is required. This fork targets the Home Assistant
app only: it retains the local RTSP, FFmpeg and preload pipeline, not upstream
web pages, WebRTC, HomeKit, cloud providers or tunnel modules. Home Assistant
creates the camera entity and supplies HLS to Alexa; the app does not serve HLS.

For an optional legacy MPEG-TS HLS compatibility camera, see
[`Local HLS Camera`](custom_components/local_hls_camera/README.md). This separately
installed Home Assistant integration leaves the app and Core code unchanged.
It was verified with a live picture on an Echo Show 15 (first generation) on
2026-10-11 with Home Assistant 2026.10.1. This is a device-specific result, not
a guarantee for every Echo or camera. HACS installs the integration directly
from this repository; the container app remains the RTSP/encoding backend.

## Install in Home Assistant

Add this repository under **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc Chainguard**, enter the camera settings on its Configuration
tab, and start it. No manual YAML file is needed. Functionality, all options,
latency tradeoffs and vendor-specific examples are documented in
[`home-assistant/DOCS.md`](home-assistant/DOCS.md).

The published image is:

```text
ghcr.io/rainerleber/go2rtc-chainguard
```

Only `amd64` and `arm64` are supported.

## Build and supply-chain controls

[`chainguard-image.yml`](.github/workflows/chainguard-image.yml) is the container
build and release workflow. It:

- uses Go 1.27.2 for tests and requires the Chainguard builder to be Go 1.27;
- resolves public Chainguard Go and Wolfi Base images to immutable digests;
- verifies both base-image Sigstore signatures before use;
- runs the complete Go test suite, `go vet`, and a clean production build;
- installs Wolfi's APK-signed FFmpeg 9 package;
- verifies `libx264` and AAC and performs real H.264 scale/pad and AAC
  transcodes matching the Alexa stream;
- publishes `amd64` and `arm64` images with immutable `YYYY.MM.BUILD` CalVer tags;
- emits an SBOM and provenance and keylessly signs the resulting manifest; and
- rebuilds every Monday to consume current Chainguard and Wolfi security fixes.

All third-party GitHub Actions are pinned to commit hashes. The validation job
has read-only repository access; write permissions exist only in the `master`
publish job.

[`local-hls-camera.yml`](.github/workflows/local-hls-camera.yml) separately tests
the optional HA integration against its supported baseline and the latest HA
release, on changes and every Monday. It has read-only repository permissions,
uses synthetic camera fixtures, and does not deploy to anyone's Home Assistant.

## Install the optional HLS integration through HACS

In HACS, add `rainerleber/go2rtc` as a **custom repository**, category
**Integration**, then download **Local HLS Camera** from the default branch
(`master`). HACS installs only `custom_components/local_hls_camera`, not the Go
sources or the container app. Follow the
[integration setup, security and update guide](custom_components/local_hls_camera/README.md).
The app's container CalVer and the integration's manifest version are separate;
HACS tracks the repository commit when downloading the default branch.

## Runtime security model

The Home Assistant app gets host networking and its own configuration directory
only. It has no Supervisor token, Home Assistant configuration mount, device
access, or privileged mode. The recommended configuration binds its API and
RTSP listener to loopback. There is no WebRTC listener or embedded web UI. This is enforced by the app's
generated configuration.

go2rtc can launch FFmpeg, and camera URLs contain credentials. Do not expose its
API or RTSP port to an untrusted network. Use the least-privileged local camera
account supported by your device and keep generated configuration and logs private.
An additional account is optional; it isolates credentials from the camera's
administrator account, but its actual permissions depend on the firmware.

The go2rtc program is MIT-licensed. Wolfi's FFmpeg package includes GPL media
components such as x264; exact package versions and licenses are recorded in the
published SBOM.

## Development

The required toolchain is Go 1.27.2:

```sh
go test ./...
go vet ./...
CGO_ENABLED=0 go build -buildvcs=false ./
```

The fork uses the independent Go module path
`github.com/rainerleber/go2rtc`. Links to `AlexxIT/go2rtc` identify the original
project and historical upstream issues or releases.

Container builds use [`docker/chainguard.Dockerfile`](docker/chainguard.Dockerfile).
Documentation for upstream-only features in the original project does not
describe this reduced HA app. See the app documentation for supported settings.
