# syntax=docker/dockerfile:1.7

# The workflow resolves both public Chainguard images to verified digests.
ARG GO_BUILDER_IMAGE="cgr.dev/chainguard/go:latest"
ARG RUNTIME_IMAGE="cgr.dev/chainguard/wolfi-base:latest"

FROM --platform=$BUILDPLATFORM ${GO_BUILDER_IMAGE} AS build

ARG TARGETOS
ARG TARGETARCH
USER 0
WORKDIR /src

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download && go mod verify

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go test ./...
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -buildvcs=false -ldflags "-s -w" -trimpath -o /out/go2rtc .

FROM ${RUNTIME_IMAGE} AS runtime

ARG BUILD_VERSION="dev"

USER 0

# The Wolfi package is built from source by Chainguard and brings x264 plus all
# runtime libraries through APK-signed dependencies. The resulting package set
# is captured in the image SBOM and immutable date/run image tag.
RUN apk add --no-cache ffmpeg-9.0

COPY --from=build /out/go2rtc /usr/local/bin/go2rtc

LABEL org.opencontainers.image.title="go2rtc Chainguard" \
      org.opencontainers.image.description="go2rtc rebuilt on Chainguard's Wolfi image with Wolfi FFmpeg" \
      org.opencontainers.image.source="https://github.com/rainerleber/go2rtc" \
      org.opencontainers.image.licenses="MIT AND GPL-2.0-or-later" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

EXPOSE 1984/tcp 8554/tcp 8555/tcp 8555/udp
VOLUME ["/config"]
WORKDIR /config

# Home Assistant owns the mounted app-config directory. Root inside this
# otherwise unprivileged app keeps config access compatible without privileged
# mode, device access, or host filesystem mounts.
USER 0
ENTRYPOINT ["/usr/local/bin/go2rtc"]
CMD ["-config", "/config/go2rtc.yaml"]
