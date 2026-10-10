# syntax=docker/dockerfile:1.7

# All images are resolved to verified digests by the GitHub Actions workflow.
ARG GO_BUILDER_IMAGE="registry.access.redhat.com/hi/go:1.25-builder"
ARG MEDIA_BUILDER_IMAGE="registry.access.redhat.com/hi/core-runtime:latest-builder"
ARG RUNTIME_IMAGE="registry.access.redhat.com/hi/core-runtime:latest"

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

FROM ${MEDIA_BUILDER_IMAGE} AS media-build

USER 0

# FFmpeg is not shipped in the Hummingbird repositories. Build the narrowly
# scoped media toolchain from checksum-verified upstream source archives. This
# stage intentionally runs on TARGETPLATFORM so the same recipe works under
# Buildx/QEMU for amd64 and arm64 without an untrusted cross toolchain.
RUN dnf install -y --setopt=install_weak_deps=False \
        gcc make pkgconf-pkg-config && \
    dnf clean all && \
    rm -rf /var/cache/dnf

COPY .build-sources/x264/ /tmp/x264/
WORKDIR /tmp/x264
RUN ./configure \
        --prefix=/opt/media \
        --enable-static \
        --disable-cli \
        --disable-opencl \
        --disable-asm && \
    make -j"$(getconf _NPROCESSORS_ONLN)" && \
    make install && \
    test -s /opt/media/lib/libx264.a && \
    PKG_CONFIG_PATH=/opt/media/lib/pkgconfig pkg-config --modversion x264

COPY .build-sources/ffmpeg/ /tmp/ffmpeg/
WORKDIR /tmp/ffmpeg
RUN if ! PKG_CONFIG_PATH=/opt/media/lib/pkgconfig ./configure \
        --prefix=/opt/media \
        --pkg-config-flags=--static \
        --extra-cflags=-I/opt/media/include \
        --extra-ldflags=-L/opt/media/lib \
        --extra-libs="-lpthread -lm" \
        --disable-autodetect \
        --disable-debug \
        --disable-doc \
        --disable-avdevice \
        --disable-postproc \
        --disable-programs \
        --enable-ffmpeg \
        --enable-gpl \
        --enable-libx264 \
        --disable-shared \
        --enable-static; then \
      cat ffbuild/config.log; \
      exit 1; \
    fi
RUN make -j"$(getconf _NPROCESSORS_ONLN)"
RUN make install && \
    strip /opt/media/bin/ffmpeg

FROM ${RUNTIME_IMAGE} AS runtime

ARG BUILD_VERSION="dev"

COPY --from=build /out/go2rtc /usr/local/bin/go2rtc
COPY --from=media-build /opt/media/bin/ffmpeg /usr/local/bin/ffmpeg

LABEL org.opencontainers.image.title="go2rtc Hummingbird" \
      org.opencontainers.image.description="go2rtc rebuilt on Red Hat Hardened Images / Project Hummingbird" \
      org.opencontainers.image.source="https://github.com/rainerleber/go2rtc" \
      org.opencontainers.image.licenses="MIT AND GPL-2.0-or-later" \
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
ENTRYPOINT ["/usr/local/bin/go2rtc"]
CMD ["-config", "/config/go2rtc.yaml"]
