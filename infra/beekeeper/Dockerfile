FROM jlesage/baseimage-gui:debian-12-v4.14.0

ARG TARGETARCH
ENV APP_NAME="Beekeeper Studio" \
    VNC_LOCALHOST_ONLY=1 \
    WEB_FILE_MANAGER=0 \
    WEB_TERMINAL=0

RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) checksum=0caa2388da9c1dd5494446977269053c00c9a309b7f893689d58c569282e3636 ;; \
      arm64) checksum=359673b654df6301ca1f39014c8253b3816854511c57aa1c120615c19409a057 ;; \
      *) echo "Unsupported Beekeeper Studio architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    add-pkg ca-certificates curl dbus-x11 libasound2 libgbm1 libgtk-3-0 libnotify4 libnss3 libsecret-1-0 libx11-xcb1 libxss1 libxtst6; \
    curl --fail --silent --show-error --location --retry 3 --output /tmp/beekeeper.deb \
      "https://github.com/beekeeper-studio/beekeeper-studio/releases/download/v6.2.2/beekeeper-studio_6.2.2_${TARGETARCH}.deb"; \
    echo "$checksum  /tmp/beekeeper.deb" | sha256sum -c -; \
    dpkg-deb -x /tmp/beekeeper.deb /tmp/beekeeper; \
    mv "/tmp/beekeeper/opt/Beekeeper Studio" /opt/beekeeper-studio; \
    rm -rf /tmp/beekeeper /tmp/beekeeper.deb; \
    rm -rf /var/lib/apt/lists/*

COPY --chmod=755 startapp.sh /startapp.sh
