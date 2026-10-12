# go2rtc and Local HLS Camera for Home Assistant

This fork packages [go2rtc](https://github.com/AlexxIT/go2rtc) as a small,
independent Home Assistant app. It does not require the upstream app catalog
and does not consume the upstream container image.

The app accepts vendor-independent RTSP cameras and either relays their stream
unchanged or produces a warm H.264/AAC compatibility stream. Structured settings
control names, resolution, frame rate, bitrate and keyframe spacing. Scaling
preserves the source aspect ratio, including portrait doorbells. No Reolink
cloud or browser workaround is required. This fork targets the Home Assistant
app only: it retains the local RTSP, FFmpeg and preload pipeline, not upstream
web pages, WebRTC, HomeKit, cloud providers or tunnel modules. The app owns
encoding, MPEG-TS HLS, bounded RAM buffering, reconnection and JPEG snapshots.
Home Assistant owns the entity, permissions, signed HTTPS routes and native Alexa.

For native Alexa playback, install the small
[`Local HLS Camera` bridge](custom_components/local_hls_camera/README.md) through
HACS. It forwards app media through HA's authenticated server, without encoding,
demuxing, a segment ring, Core patches or additional app permissions.
No intermediate Generic Camera is needed. Sustained native Echo Show 15
playback with App 2026.10.30 and bridge 2026.10.4 was user-confirmed on
2026-10-12 after an App-only update and a camera-only test without a gong.
Synthetic end-to-end tests also cover the app-owned backend, signed playlist
reloads and restart revocation. This does not guarantee every Echo/camera;
verify sustained playback on the actual device after installation or updates.
HLS sequences start at zero for each worker generation to accommodate older
players with 32-bit playlist parsers. Generation-scoped URLs still reject old
media after reconnects; see the [private HLS contract](internal/hls/README.md).

## Install in Home Assistant

Add this repository under **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc**, enter the camera settings on its Configuration
tab, and start it. No manual YAML file is needed. Functionality, all options,
latency tradeoffs and vendor-specific examples are documented in
[`home-assistant/DOCS.md`](home-assistant/DOCS.md).

The published image is:

```text
ghcr.io/rainerleber/go2rtc-chainguard
```

Only `amd64` and `arm64` are supported.

## Build and supply-chain controls

[Container image](.github/workflows/chainguard-image.yml) is the container build
and release workflow. It:

- uses Go 1.27.2 for tests and requires the builder to be Go 1.27;
- resolves the configured Go builder and Wolfi runtime images to immutable digests;
- verifies both base-image Sigstore signatures before use;
- runs the complete Go test suite, `go vet`, and a clean production build;
- installs Wolfi's APK-signed FFmpeg 9 package;
- verifies `libx264` and AAC and performs real H.264 scale/pad, AAC,
  RAM-only MPEG-TS HLS and snapshot tests matching the Alexa stream;
- publishes `amd64` and `arm64` images with immutable `YYYY.MM.BUILD` CalVer tags;
- emits an SBOM and provenance and keylessly signs the resulting manifest; and
- rebuilds every Monday at 03:17 UTC to consume current base-image security fixes.

Relevant source pushes trigger validation on any branch. Only `master` publishes
images to GHCR, on a push, the weekly schedule, or a manual workflow run.
After publishing and signing both the immutable CalVer tag and `latest`, the
workflow commits the new version to `home-assistant/config.yaml`. Home Assistant
downloads that published image when the app is installed or updated; the workflow
does not restart or deploy to Home Assistant. Images are not uploaded from a
local development machine. Changes limited to the root README or the
`custom_components/local_hls_camera` tree do not trigger a container rebuild.

The existing app slug, registry image path and workflow filename are retained
as compatibility identifiers, not display names. This preserves installed app
configuration/data, published image references and the workflow's CalVer build
counter. The app and image descriptions use only the functional `go2rtc` name.

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

Container builds use [`docker/Dockerfile`](docker/Dockerfile).
Documentation for upstream-only features in the original project does not
describe this reduced HA app. See the app documentation for supported settings.
