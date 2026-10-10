# syntax=docker/dockerfile:1.7

# Both images are resolved to a verified digest by the GitHub Actions workflow.
ARG GO_BUILDER_IMAGE="registry.access.redhat.com/hi/go:1.25-builder"
ARG RUNTIME_IMAGE="registry.access.redhat.com/hi/python:3.13-builder"

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
    go test ./... && \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -buildvcs=true -ldflags "-s -w" -trimpath -o /out/go2rtc .

FROM ${RUNTIME_IMAGE} AS runtime

ARG BUILD_VERSION="dev"

USER 0

# ffmpeg-free is supplied by the signed Hummingbird package repositories. The
# workflow verifies at build time that an H.264 encoder is actually available.
RUN dnf install -y --setopt=install_weak_deps=False ffmpeg-free tini && \
    dnf clean all && \
    rm -rf /var/cache/dnf

COPY --from=build /out/go2rtc /usr/local/bin/go2rtc

LABEL org.opencontainers.image.title="go2rtc Hummingbird" \
      org.opencontainers.image.description="go2rtc rebuilt on Red Hat Hardened Images / Project Hummingbird" \
      org.opencontainers.image.source="https://github.com/rainerleber/go2rtc" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

EXPOSE 1984/tcp 8554/tcp 8555/tcp 8555/udp
VOLUME ["/config"]
WORKDIR /config

# Home Assistant owns the mounted app-config directory. Running as root inside
# this otherwise unprivileged app keeps WebUI/config writes compatible without
# granting privileged mode or host filesystem mounts.
USER 0
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/go2rtc"]
CMD ["-config", "/config/go2rtc.yaml"]
