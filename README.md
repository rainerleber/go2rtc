# go2rtc Chainguard for Home Assistant

This fork packages [go2rtc](https://github.com/AlexxIT/go2rtc) as a small,
independent Home Assistant app. It does not require the upstream app catalog
and does not consume the upstream container image.

The fork exists for one concrete local use case: normalize a Reolink doorbell
RTSP stream to H.264/AAC in a preloaded 1280x720 frame that Alexa/Echo Show can consume. The
go2rtc source remains broadly compatible with upstream so security and protocol
updates can still be reviewed and merged.

## Install in Home Assistant

Add this repository under **Settings → Apps → App store → Repositories**:

```text
https://github.com/rainerleber/go2rtc
```

Install **go2rtc Chainguard**, create its `go2rtc.yaml`, and only then start the
app. The complete loopback-only Reolink example is in
[`home-assistant/DOCS.md`](home-assistant/DOCS.md).

The published image is:

```text
ghcr.io/rainerleber/go2rtc-chainguard
```

Only `amd64` and `arm64` are supported.

## Build and supply-chain controls

[`chainguard-image.yml`](.github/workflows/chainguard-image.yml) is the only
build and release workflow. It:

- uses Go 1.27.2 for tests and requires the Chainguard builder to be Go 1.27;
- resolves public Chainguard Go and Wolfi Base images to immutable digests;
- verifies both base-image Sigstore signatures before use;
- runs the complete Go test suite, `go vet`, and a clean production build;
- installs Wolfi's APK-signed FFmpeg 9 package;
- verifies `libx264` and AAC and performs real H.264 scale/pad and AAC
  transcodes matching the Alexa stream;
- publishes `amd64` and `arm64` images with immutable `YYYY.MM.DD.RUN` tags;
- emits an SBOM and provenance and keylessly signs the resulting manifest; and
- rebuilds every Monday to consume current Chainguard and Wolfi security fixes.

All third-party GitHub Actions are pinned to commit hashes. The validation job
has read-only repository access; write permissions exist only in the `master`
publish job.

## Runtime security model

The Home Assistant app gets host networking and its own configuration directory
only. It has no Supervisor token, Home Assistant configuration mount, device
access, or privileged mode. The recommended configuration binds its API and
RTSP listener to loopback and disables WebRTC.

go2rtc can launch FFmpeg, and camera URLs contain credentials. Do not expose its
API or RTSP port to an untrusted network. Use a dedicated camera account with
live-view permission only and keep `go2rtc.yaml` and logs private.

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
Upstream feature documentation is maintained in the
[original go2rtc repository](https://github.com/AlexxIT/go2rtc).
